"""사진 한 장의 용량 줄임, EXIF(사진 정보) 유지.
회전은 하지 않는다: 픽셀과 회전 정보를 원본 그대로 두어 원본과 똑같은 방향으로 보이게 한다."""
import io
import os

import piexif
from PIL import Image

MIN_SIDE = 200  # 이보다 작아지면 더 줄이지 않고 실패로 처리

# 처리 방식 (결과 요약에 쓰임)
QUALITY = "quality"  # 화질만 조절
RESIZE = "resize"    # 가로·세로도 줄임
COPY = "copy"        # 그대로 복사


class ShrinkError(Exception):
    """사용자에게 보여줄 쉬운 말 설명을 담은 오류."""


def _clean_ifd(exif_dict):
    """piexif가 저장하지 못하는 태그를 하나씩 골라 뺀다."""
    for ifd in ("0th", "Exif", "GPS", "Interop"):
        tags = exif_dict.get(ifd) or {}
        for tag in list(tags):
            try:
                piexif.dump({ifd: {tag: tags[tag]}})
            except Exception:
                del tags[tag]


def make_exif(img, size):
    """원본 EXIF에서 미리보기를 빼고, 크기는 새 크기로 바꾼 bytes. 회전 정보는 원본 그대로."""
    raw = img.info.get("exif")
    if not raw:
        return None
    try:
        d = piexif.load(raw)
    except Exception:
        return None
    d["thumbnail"] = None
    d["1st"] = {}
    exif_ifd = d.setdefault("Exif", {})
    if piexif.ExifIFD.PixelXDimension in exif_ifd:
        exif_ifd[piexif.ExifIFD.PixelXDimension] = size[0]
    if piexif.ExifIFD.PixelYDimension in exif_ifd:
        exif_ifd[piexif.ExifIFD.PixelYDimension] = size[1]
    try:
        return piexif.dump(d)
    except Exception:
        pass
    exif_ifd.pop(piexif.ExifIFD.MakerNote, None)
    try:
        return piexif.dump(d)
    except Exception:
        pass
    _clean_ifd(d)
    try:
        return piexif.dump(d)
    except Exception:
        return None


def encode(img, quality, exif, icc):
    buf = io.BytesIO()
    kwargs = {"quality": quality, "optimize": True}
    if exif:
        kwargs["exif"] = exif
    if icc:
        kwargs["icc_profile"] = icc
    img.save(buf, "JPEG", **kwargs)
    return buf.getvalue()


def fit_quality(img, cfg, exif, icc):
    """목표 용량 이하가 되는 가장 높은 화질로 저장한 bytes. 하한에서도 크면 None."""
    max_bytes = cfg["max_bytes"]
    lo, hi = cfg["quality_min"], cfg["quality_max"]
    data = encode(img, lo, exif, icc)
    if len(data) > max_bytes:
        return None
    best = data
    lo += 1
    while lo <= hi:
        mid = (lo + hi) // 2
        data = encode(img, mid, exif, icc)
        if len(data) <= max_bytes:
            best = data
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def shrink(src_path, cfg):
    """사진 한 장을 줄인다.

    반환: (data, method)
      - method가 COPY이면 data는 None (파일을 그대로 복사하면 됨)
      - 그 외에는 data가 저장할 JPG bytes
    """
    size = os.path.getsize(src_path)
    try:
        img = Image.open(src_path)
        img.load()
    except Exception:
        raise ShrinkError("사진 파일이 손상되었거나 열 수 없어요")

    if size <= cfg["max_bytes"]:
        return None, COPY

    icc = img.info.get("icc_profile")
    base = img
    if base.mode not in ("RGB", "L", "CMYK"):
        base = base.convert("RGB")

    data = fit_quality(base, cfg, make_exif(img, base.size), icc)
    if data is not None:
        return data, QUALITY

    ow, oh = base.size
    scale = 1.0
    while True:
        # 매번 원래 크기에서 계산해야 반올림 오차가 쌓이지 않아 가로:세로 비율이 그대로 유지된다
        scale *= cfg["scale_step"]
        w = round(ow * scale)
        h = round(w * oh / ow)
        if min(w, h) < MIN_SIDE:
            raise ShrinkError("사진을 아무리 줄여도 목표 용량 이하가 되지 않아요")
        resized = base.resize((w, h), Image.LANCZOS)
        data = fit_quality(resized, cfg, make_exif(img, (w, h)), icc)
        if data is not None:
            return data, RESIZE
