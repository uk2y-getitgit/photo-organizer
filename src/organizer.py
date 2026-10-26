"""폴더 정리: 임시 파일 → 확인 → 이름 바꾸기 → 원본 이동, 정리 기록, 되돌리기."""
import ctypes
import errno
import hashlib
import json
import msvcrt
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image
from send2trash import send2trash

import processor

JPG_EXTS = (".jpg", ".jpeg")
TMP_PREFIX = ".tmp_"
HISTORY_NAME = ".정리기록.json"

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_NORMAL = 0x80


# ---------- 공통 도우미 ----------

def _attrs(path):
    a = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    return 0 if a == 0xFFFFFFFF else a


def _set_hidden(path, hidden):
    ctypes.windll.kernel32.SetFileAttributesW(
        str(path), FILE_ATTRIBUTE_HIDDEN if hidden else FILE_ATTRIBUTE_NORMAL)


def unique_path(folder, name):
    """folder/name이 이미 있으면 '이름 (1).jpg'처럼 번호를 붙인 경로."""
    p = Path(folder) / name
    if not p.exists():
        return p
    stem, ext = os.path.splitext(name)
    i = 1
    while (Path(folder) / f"{stem} ({i}){ext}").exists():
        i += 1
    return Path(folder) / f"{stem} ({i}){ext}"


def friendly_error(e):
    """오류를 쉬운 말로 바꾼다."""
    if isinstance(e, processor.ShrinkError):
        return str(e)
    if isinstance(e, PermissionError):
        return "다른 프로그램이 파일을 사용 중이거나 권한이 없어요"
    if isinstance(e, OSError) and e.errno == errno.ENOSPC:
        return "저장 공간이 부족해요"
    if isinstance(e, FileNotFoundError):
        return "처리 중에 파일이 사라졌어요"
    return f"알 수 없는 오류가 났어요 ({e})"


class AlreadyRunning(Exception):
    pass


class FolderLock:
    """같은 폴더에서 동시에 두 번 실행되지 않게 막는 잠금 파일.
    잠금 파일은 임시 폴더에 두므로 사진 폴더를 어지럽히지 않고,
    프로그램이 비정상 종료돼도 윈도우가 잠금을 자동으로 풀어 준다."""

    def __init__(self, folder):
        key = hashlib.md5(os.path.normcase(os.path.abspath(folder)).encode("utf-8")).hexdigest()
        self.path = Path(tempfile.gettempdir()) / f"현장사진정리기_{key}.lock"
        self.f = None

    def __enter__(self):
        self.f = open(self.path, "a+")
        try:
            msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.f.close()
            raise AlreadyRunning()
        return self

    def __exit__(self, *exc):
        try:
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.f.close()
        try:
            self.path.unlink()
        except OSError:
            pass


# ---------- 정리 기록 ----------

def load_history(folder, cfg):
    path = Path(folder) / cfg["original_folder"] / HISTORY_NAME
    try:
        runs = json.loads(path.read_text(encoding="utf-8"))
        return runs if isinstance(runs, list) else []
    except (OSError, ValueError):
        return []


def save_history(folder, cfg, runs):
    path = Path(folder) / cfg["original_folder"] / HISTORY_NAME
    if not runs:
        if path.exists():
            _set_hidden(path, False)
            path.unlink()
        return
    if path.exists():
        _set_hidden(path, False)  # 숨김 파일은 바로 덮어쓸 수 없어서 잠시 푼다
    path.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    _set_hidden(path, True)


# ---------- 정리 ----------

@dataclass
class OrganizeResult:
    total: int = 0                 # 정리 대상 사진 수
    done: int = 0                  # 성공한 사진 수
    counts: dict = field(default_factory=lambda: {processor.QUALITY: 0, processor.RESIZE: 0, processor.COPY: 0})
    bytes_before: int = 0
    bytes_after: int = 0
    skipped: list = field(default_factory=list)  # (파일 이름, 이유)
    failed: list = field(default_factory=list)   # (파일 이름, 이유)


def scan(folder, cfg):
    """정리할 사진 목록과 건너뛸 파일 목록."""
    suffix = cfg["suffix"]
    targets, skipped = [], []
    for entry in sorted(os.scandir(folder), key=lambda e: e.name.lower()):
        if not entry.is_file():
            continue
        name = entry.name
        if name.startswith(TMP_PREFIX):
            continue
        if _attrs(entry.path) & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
            continue  # Thumbs.db, desktop.ini 같은 윈도우 숨김 파일
        stem, ext = os.path.splitext(name)
        if ext.lower() not in JPG_EXTS:
            skipped.append((name, "JPG 아님"))
        elif stem.endswith(suffix):
            continue  # 이미 줄인 사진 — 결과 창에 매번 나오면 번거로우니 조용히 넘어간다
        elif (Path(folder) / f"{stem}{suffix}{ext}").exists():
            skipped.append((name, "이미 정리한 사진"))
        else:
            targets.append(name)
    return targets, skipped


def _verify(path, max_bytes):
    if os.path.getsize(path) > max_bytes:
        raise processor.ShrinkError("줄인 사진이 목표 용량보다 커요")
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception:
        raise processor.ShrinkError("줄인 사진이 정상적으로 열리지 않아요")


def process_one(folder, name, cfg):
    """사진 한 장을 안전한 순서로 처리한다. 반환: (방식, 원본 크기, 결과 크기, 원본이 옮겨진 이름, 줄인 파일 이름)"""
    folder = Path(folder)
    src = folder / name
    stem, ext = os.path.splitext(name)
    tmp = folder / f"{TMP_PREFIX}{name}"
    final = folder / f"{stem}{cfg['suffix']}{ext}"
    st = os.stat(src)
    renamed = False
    try:
        # 1. 임시 파일 만들기
        data, method = processor.shrink(src, cfg)
        if data is None:
            shutil.copy2(src, tmp)
        else:
            tmp.write_bytes(data)
        # 2. 임시 파일 확인
        _verify(tmp, cfg["max_bytes"])
        # 3. _줄임 이름으로 바꾸고 수정한 날짜를 원본과 맞춤
        if final.exists():
            raise processor.ShrinkError("같은 이름의 _줄임 파일이 이미 있어요")
        os.rename(tmp, final)
        renamed = True
        os.utime(final, ns=(st.st_atime_ns, st.st_mtime_ns))
        # 4. 원본을 "원본" 폴더로 옮김
        orig_dir = folder / cfg["original_folder"]
        orig_dir.mkdir(exist_ok=True)
        dest = unique_path(orig_dir, name)
        os.rename(src, dest)
        return method, st.st_size, os.path.getsize(final), dest.name, final.name
    except Exception:
        # 실패하면 이번에 만든 파일만 지우고 원본은 제자리에 둔다
        for p in (tmp, final if renamed else None):
            if p is not None and p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        raise


def organize(folder, cfg, targets, skipped, progress=None):
    """targets 사진을 차례로 정리한다. progress(done_index, total, name)로 진행 상황을 알린다."""
    result = OrganizeResult(total=len(targets), skipped=list(skipped))
    runs = load_history(folder, cfg)
    run = None
    for i, name in enumerate(targets):
        if progress:
            progress(i, len(targets), name)
        try:
            method, before, after, moved_to, reduced = process_one(folder, name, cfg)
        except Exception as e:
            result.failed.append((name, friendly_error(e)))
            continue
        result.done += 1
        result.counts[method] += 1
        result.bytes_before += before
        result.bytes_after += after
        if run is None:
            run = {"time": datetime.now().isoformat(timespec="seconds"), "items": []}
            runs.append(run)
        run["items"].append({"original": name, "moved_to": moved_to, "reduced": reduced})
        try:
            save_history(folder, cfg, runs)  # 한 장마다 저장해 도중에 꺼져도 기록이 남게
        except OSError:
            pass
    if progress:
        progress(len(targets), len(targets), "")
    return result


# ---------- 되돌리기 ----------

@dataclass
class UndoResult:
    restored: int = 0
    trashed: int = 0
    renamed: list = field(default_factory=list)  # (원래 이름, 바뀐 이름)
    failed: list = field(default_factory=list)   # (파일 이름, 이유)


def last_run(folder, cfg):
    runs = load_history(folder, cfg)
    return runs[-1] if runs else None


def undo_last(folder, cfg, progress=None):
    """가장 최근 정리 1회를 되돌린다."""
    folder = Path(folder)
    orig_dir = folder / cfg["original_folder"]
    runs = load_history(folder, cfg)
    result = UndoResult()
    if not runs:
        return result
    run = runs[-1]
    remaining = []
    items = run.get("items", [])
    for i, item in enumerate(items):
        if progress:
            progress(i, len(items), item.get("original", ""))
        try:
            original, moved_to, reduced = item["original"], item["moved_to"], item["reduced"]
        except (KeyError, TypeError):
            continue
        src = orig_dir / moved_to
        if not src.exists():
            result.failed.append((original, "원본 폴더에서 이 사진을 찾을 수 없어요"))
            continue
        # 1. 원본을 제자리로 (같은 이름이 있으면 번호 붙이기)
        dest = unique_path(folder, original)
        try:
            os.rename(src, dest)
        except Exception as e:
            result.failed.append((original, friendly_error(e)))
            remaining.append(item)  # 다음에 다시 되돌릴 수 있게 기록에 남김
            continue
        result.restored += 1
        if dest.name != original:
            result.renamed.append((original, dest.name))
        # 2. 줄인 사진은 휴지통으로
        red = folder / reduced
        if red.exists():
            try:
                send2trash(str(red))
                result.trashed += 1
            except Exception as e:
                result.failed.append((reduced, "휴지통으로 보내지 못했어요: " + friendly_error(e)))
    if progress:
        progress(len(items), len(items), "")

    if remaining:
        run["items"] = remaining
    else:
        runs.pop()
    try:
        save_history(folder, cfg, runs)
    except OSError:
        pass
    # "원본" 폴더가 비면 지운다
    try:
        if orig_dir.is_dir() and not any(orig_dir.iterdir()):
            orig_dir.rmdir()
    except OSError:
        pass
    return result
