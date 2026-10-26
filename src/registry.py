"""우클릭 메뉴 등록·해제 (관리자 권한 없이 현재 사용자 설정에만)."""
import os
import shutil
import sys
import winreg
from pathlib import Path

import config
import ui

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "현장사진정리기"
EXE_NAME = "현장사진정리기.exe"
SHELL_KEY = r"Software\Classes\Directory\shell"
# (레지스트리 키 이름, 메뉴에 보이는 이름, 실행 옵션)
MENUS = [
    ("PhotoOrganizer", "사진 정리", ""),
    ("PhotoOrganizerUndo", "사진 정리 되돌리기", "--undo "),
]


def install():
    if not getattr(sys, "frozen", False):
        ui.error("--install은 .exe로 만든 뒤에 실행해 주세요.")
        return
    if not ui.ask("폴더 우클릭 메뉴에 '사진 정리'와 '사진 정리 되돌리기'를 등록할까요?\n\n"
                  f"프로그램은 아래 위치에 복사돼요.\n{APP_DIR}"):
        return
    src = Path(sys.executable).resolve()
    target = APP_DIR / EXE_NAME
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if src != target.resolve():
            shutil.copy2(src, target)
        cfg_target = APP_DIR / config.CONFIG_NAME
        cfg_src = src.parent / config.CONFIG_NAME
        if not cfg_target.exists():  # 이미 있는 설정은 덮어쓰지 않는다
            if cfg_src.exists():
                shutil.copy2(cfg_src, cfg_target)
            else:
                import json
                cfg_target.write_text(json.dumps(config.DEFAULTS, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    except PermissionError:
        ui.error("프로그램을 복사하지 못했어요.\n사진 정리 창이 열려 있다면 모두 닫고 다시 실행해 주세요.")
        return
    except OSError as e:
        ui.error(f"프로그램을 복사하지 못했어요.\n({e})")
        return

    for key, label, option in MENUS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{SHELL_KEY}\{key}") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, label)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, f'"{target}"')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{SHELL_KEY}\{key}\command") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, f'"{target}" {option}"%1"')
    ui.info("등록했어요.\n\n폴더를 우클릭 → '더 많은 옵션 표시' 안에서 '사진 정리'를 찾을 수 있어요.\n"
            "(Shift를 누른 채 우클릭해도 바로 보여요.)")


def uninstall():
    if not ui.ask("폴더 우클릭 메뉴에서 '사진 정리'와 '사진 정리 되돌리기'를 뺄까요?"):
        return
    for key, _, _ in MENUS:
        for sub in (rf"{SHELL_KEY}\{key}\command", rf"{SHELL_KEY}\{key}"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except FileNotFoundError:
                pass
    ui.info("우클릭 메뉴에서 뺐어요.\n\n프로그램 파일을 완전히 지우려면 아래 폴더를 직접 지우면 돼요.\n"
            f"{APP_DIR}")
