"""用户可调参数：读写本程序自己的 data/settings.json。

机器人那边完全不涉及。
"""
from __future__ import annotations

import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("ZZYANG_DATA_HOME") or os.path.join(BASE, "data")
PATH = os.path.join(DATA_DIR, "settings.json")

DEFAULTS = {
    "bot_root": "",
    "refresh_seconds": 30,
    "active_minutes": 30,
    "quiet_minutes": 90,
    "timeline_limit": 40,
    "page_size": 60,
}

LIMITS = {
    "refresh_seconds": (5, 600),
    "active_minutes": (1, 1440),
    "quiet_minutes": (1, 10080),
    "timeline_limit": (5, 500),
    "page_size": (10, 500),
}

_cache: dict | None = None


def _sanitize(raw: dict) -> dict:
    out = dict(DEFAULTS)

    root = raw.get("bot_root")
    if isinstance(root, str):
        out["bot_root"] = root.strip()[:260]

    for key, (lo, hi) in LIMITS.items():
        if key not in raw:
            continue
        try:
            val = int(raw[key])
        except (TypeError, ValueError):
            continue
        out[key] = max(lo, min(hi, val))
    return out


def load() -> dict:
    """读配置；文件不存在就生成默认值；写坏了就回退默认值。"""
    global _cache
    if _cache is not None:
        return dict(_cache)

    settings = dict(DEFAULTS)
    note = ""
    if os.path.exists(PATH):
        try:
            # utf-8-sig：允许记事本保存时带的 BOM
            with open(PATH, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                settings = _sanitize(raw)
            else:
                note = "settings.json 不是对象，已使用默认设置"
        except Exception as e:
            note = f"settings.json 读不出来（{type(e).__name__}），已使用默认设置"
    else:
        try:
            save(DEFAULTS)
        except Exception:
            pass

    _cache = settings
    if note:
        settings["_note"] = note
    return dict(settings)


def save(raw: dict) -> None:
    global _cache
    os.makedirs(DATA_DIR, exist_ok=True)
    clean = _sanitize(raw)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)
    _cache = clean


def reload() -> dict:
    global _cache
    _cache = None
    return load()
