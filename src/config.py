"""config.json 읽기. 파일이 없거나 값이 잘못되면 기본값을 쓴다."""
import json
import sys
from pathlib import Path

DEFAULTS = {
    "max_bytes": 500000,
    "quality_max": 95,
    "quality_min": 70,
    "scale_step": 0.9,
    "suffix": "_줄임",
    "original_folder": "원본",
}

CONFIG_NAME = "config.json"


def base_dir():
    """.exe로 실행하면 .exe가 있는 폴더, 개발 중에는 프로젝트 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _valid(key, value, cfg):
    if key == "max_bytes":
        return isinstance(value, int) and not isinstance(value, bool) and value > 10000
    if key in ("quality_max", "quality_min"):
        return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 95
    if key == "scale_step":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.1 <= value < 1
    if key == "suffix":
        return isinstance(value, str) and value.strip() != "" and not any(c in value for c in '\\/:*?"<>|')
    if key == "original_folder":
        return isinstance(value, str) and value.strip() != "" and not any(c in value for c in '\\/:*?"<>|')
    return False


def load(path=None):
    cfg = dict(DEFAULTS)
    path = Path(path) if path else base_dir() / CONFIG_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    for key in DEFAULTS:
        if key in data and _valid(key, data[key], cfg):
            cfg[key] = data[key]
    if cfg["quality_min"] > cfg["quality_max"]:
        cfg["quality_min"] = DEFAULTS["quality_min"]
        cfg["quality_max"] = DEFAULTS["quality_max"]
    return cfg
