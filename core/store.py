"""这个 app 自己的数据：星标与批注。

只写本程序目录下的文件。不会写入机器人那边的任何东西，也不改变它日记的顺序。

数据结构（v2）：
{
  "version": 2,
  "items": {
    "<指纹>": {"time": "...", "preview": "...", "starred_at": "...", "note": "我写的批注"}
  }
}
v1（没有 version、没有 note 字段）仍可读取。
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
STARS = os.path.join(DATA_DIR, "stars.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backup")
KEEP_BACKUPS = 5

_lock = threading.Lock()


def _empty() -> dict:
    return {"version": 2, "items": {}}


def _load() -> dict:
    if not os.path.exists(STARS):
        return _empty()
    try:
        with open(STARS, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return _empty()
    if not isinstance(data, dict) or "items" not in data:
        return _empty()
    items = data["items"]
    if not isinstance(items, dict):
        return _empty()
    # v1 兼容：补齐字段
    for key, val in list(items.items()):
        if not isinstance(val, dict):
            items.pop(key)
            continue
        val.setdefault("time", "")
        val.setdefault("preview", "")
        val.setdefault("starred_at", "")
        val.setdefault("note", "")
    data["version"] = 2
    return data


def _backup_rotate() -> None:
    """保留最近几份，误删可恢复。"""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if os.path.exists(STARS):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(STARS, os.path.join(BACKUP_DIR, f"stars-{stamp}.json"))
        files = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.startswith("stars-") and f.endswith(".json")]
        )
        for old in files[:-KEEP_BACKUPS]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old))
            except OSError:
                pass
    except Exception:
        pass


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    data["version"] = 2
    tmp = STARS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STARS)


def all_stars() -> dict:
    with _lock:
        return _load()["items"]


def toggle(entry_id: str, time_text: str, preview: str) -> bool:
    """返回切换后的状态：True 表示已标星。"""
    with _lock:
        data = _load()
        items = data["items"]
        if entry_id in items:
            del items[entry_id]
            starred = False
        else:
            _backup_rotate()
            items[entry_id] = {
                "time": time_text,
                "preview": preview[:60],
                "starred_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "note": "",
            }
            starred = True
        _save(data)
        return starred


def set_note(entry_id: str, note: str) -> dict:
    """给某条星标写批注（必须先标星）。"""
    with _lock:
        data = _load()
        item = data["items"].get(entry_id)
        if item is None:
            return {"ok": False, "error": "这条还没有标星，先标星再加批注"}
        _backup_rotate()
        item["note"] = (note or "").strip()[:500]
        _save(data)
        return {"ok": True, "items": data["items"]}
