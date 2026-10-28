"""只读数据层：读取机器人的日记、读书进度、对话痕迹与运行状态。

这里的所有操作都是只读的。不会写入、修改、移动被监测目录下的任何文件，
数据库一律以 mode=ro 打开。

被监测目录（BOT_ROOT）的确定顺序：
1. 环境变量 ZZYANG_DATA_ROOT（测试用）
2. 本程序 data/settings.json 里的 bot_root（用户在首次运行界面里选的）
3. 都没有就是空的 —— 界面会引导用户去设置

仓库里不写死任何人的路径。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import time
from datetime import datetime, timedelta

from . import settings

DEFAULT_BOT_ROOT = ""

BOT_ROOT = ""
PLUGIN_DATA = ""
JOURNAL = ""
PROFILE_META = ""
PLUGIN_CFG = ""
DB = ""
BOOKS_DIR = ""
ROOT_SOURCE = ""

TIME_FMT = "%Y-%m-%d %H:%M"


def _derive(root: str) -> None:
    """由 BOT_ROOT 推导出所有具体路径。"""
    global BOT_ROOT, PLUGIN_DATA, JOURNAL, PROFILE_META, PLUGIN_CFG, DB, BOOKS_DIR
    BOT_ROOT = root
    PLUGIN_DATA = os.path.join(root, "plugins", "astrbot_plugin_edge_tts", "data")
    JOURNAL = os.path.join(PLUGIN_DATA, "journal.jsonl")
    PROFILE_META = os.path.join(PLUGIN_DATA, "profile_meta.json")
    PLUGIN_CFG = os.path.join(root, "config", "astrbot_plugin_edge_tts_config.json")
    DB = os.path.join(root, "data_v4.db")
    BOOKS_DIR = os.path.join(PLUGIN_DATA, "books")


def resolve_root_input(path: str):
    """把用户填的路径整理成真正的 instance\\data；认不出来返回 None。

    允许用户填：
    - AstrBot 的 data 目录本身（含 data_v4.db 或 plugins）
    - AstrBot 根目录（含 instance\\data）
    """
    if not path:
        return None
    p = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
    candidates = [p, os.path.join(p, "instance", "data"), os.path.join(p, "data")]
    for c in candidates:
        if not os.path.isdir(c):
            continue
        has_db = os.path.exists(os.path.join(c, "data_v4.db"))
        has_plugins = os.path.isdir(os.path.join(c, "plugins"))
        if has_db or has_plugins:
            return c
    return None


def is_root_usable(root: str | None = None) -> bool:
    r = root if root is not None else BOT_ROOT
    if not r or not os.path.isdir(r):
        return False
    return os.path.exists(os.path.join(r, "data_v4.db")) or os.path.isdir(
        os.path.join(r, "plugins")
    )


def configure_root(path: str | None = None) -> str:
    """确定并应用被监测目录，返回最终使用的路径。

    显式传入 path 时直接用它（用户在界面里设置时走这条路）。
    """
    global ROOT_SOURCE
    if path:
        _derive(path)
        ROOT_SOURCE = "settings"
        return BOT_ROOT

    root = os.environ.get("ZZYANG_DATA_ROOT")
    source = "env"
    if not root:
        cfg = settings.load()
        root = (cfg.get("bot_root") or "").strip()
        source = "settings"
    if not root:
        root = DEFAULT_BOT_ROOT
        source = "default"
    _derive(root)
    ROOT_SOURCE = source
    return root


configure_root()



# 日记类型：自己写的 / 聊天时写的 / 动作为记录
KIND_META = {
    "self": {"label": "自己写的", "tone": "self"},
    "dialogue": {"label": "聊天时写的", "tone": "dialogue"},
    "read": {"label": "读了会儿书", "tone": "read"},
    "message": {"label": "主动找你", "tone": "message"},
    "autocapture": {"label": "自动补记", "tone": "autocapture"},
}


def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def classify(content: str, auto: bool) -> str:
    c = (content or "").strip()
    if c.startswith("（自己读了会儿书）") or c.startswith("(自己读了会儿书)"):
        return "read"
    if c.startswith("（我主动找他说）") or c.startswith("(我主动找他说)"):
        return "message"
    if c.startswith("（自动补记）") or c.startswith("(自动补记)"):
        return "autocapture"
    return "self" if auto else "dialogue"


def entry_id(ts: str, content: str) -> str:
    """内容指纹：只依赖时间与正文，机器人那边改动文件也不会撞车。"""
    h = hashlib.sha1(f"{ts}\x00{content}".encode("utf-8")).hexdigest()
    return h[:16]


def parse_ts(s: str):
    s = (s or "").strip()
    for fmt in (TIME_FMT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def read_journal_detailed() -> tuple[list[dict], dict]:
    """读日记，原样返回，只做展示层的合并（不修改源文件）。"""
    out: list[dict] = []
    meta = {"missing": False, "bad_lines": 0, "total_lines": 0}
    if not os.path.exists(JOURNAL):
        meta["missing"] = True
        return out, meta
    seen: dict[str, dict] = {}
    try:
        f = open(JOURNAL, "r", encoding="utf-8", errors="replace")
    except OSError:
        meta["missing"] = True
        return out, meta
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            meta["total_lines"] += 1
            try:
                row = json.loads(line)
            except Exception:
                meta["bad_lines"] += 1
                continue
            content = str(row.get("content") or "").strip()
            ts = str(row.get("time") or "").strip()
            if not content:
                continue
            auto = bool(row.get("auto"))
            key = entry_id(ts, content)
            if key in seen:
                seen[key]["duplicates"] += 1
                continue
            dt = parse_ts(ts)
            item = {
                "id": key,
                "time": ts,
                "ts": dt.timestamp() if dt else 0,
                "date": dt.strftime("%Y-%m-%d") if dt else "未知日期",
                "clock": dt.strftime("%H:%M") if dt else "",
                "content": content,
                "kind": classify(content, auto),
                "auto": auto,
                "duplicates": 1,
                "chars": len(content),
            }
            seen[key] = item
            out.append(item)
    out.sort(key=lambda x: (x["ts"], x["time"]), reverse=True)
    return out, meta


def read_journal() -> list[dict]:
    entries, _ = read_journal_detailed()
    return entries


def _db():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=3.0)
    con.row_factory = sqlite3.Row
    return con


def read_preferences_detailed() -> tuple[dict, dict]:
    data = {}
    meta = {"ok": True, "missing": False, "error": ""}
    if not os.path.exists(DB):
        meta.update(ok=False, missing=True, error="数据库文件不存在")
        return data, meta
    try:
        con = _db()
        try:
            for row in con.execute("SELECT key, value, updated_at FROM preferences"):
                try:
                    data[row["key"]] = {
                        "val": json.loads(row["value"]).get("val"),
                        "updated_at": row["updated_at"],
                    }
                except Exception:
                    continue
        finally:
            con.close()
    except Exception as e:
        meta.update(ok=False, error=f"{type(e).__name__}: {e}")
    return data, meta


def read_preferences() -> dict:
    data, _ = read_preferences_detailed()
    return data


def read_reading_all(pref: dict | None = None) -> list[dict]:
    """所有在读的书，按最后翻页时间倒序。"""
    pref = pref if pref is not None else read_preferences()
    books = []
    for k, v in pref.items():
        if ":book_pos:" not in k:
            continue
        name = k.split(":book_pos:", 1)[1]
        try:
            pos = int(v.get("val") or 0)
        except (TypeError, ValueError):
            pos = 0
        info = {
            "book": name,
            "pos": pos,
            "total": 0,
            "updated_at": v.get("updated_at") or "",
            "percent": 0.0,
        }
        path = os.path.join(BOOKS_DIR, name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    info["total"] = len(f.read())
            except Exception:
                pass
        if info["total"]:
            info["percent"] = round(pos / info["total"] * 100, 1)
        books.append(info)
    books.sort(key=lambda b: b["updated_at"] or "", reverse=True)
    return books


def read_reading(pref: dict | None = None) -> dict:
    books = read_reading_all(pref)
    return books[0] if books else {}


def read_chat_tail(limit: int = 6, pref: dict | None = None) -> dict:
    pref = pref if pref is not None else read_preferences()
    for k, v in pref.items():
        if ":chat_log:" not in k:
            continue
        val = v.get("val")
        if not isinstance(val, list) or not val:
            continue
        msgs = []
        for m in val[-limit:]:
            role = m.get("role") or ""
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            msgs.append(
                {
                    "role": "me" if role == "user" else "bot",
                    "text": content[:180],
                }
            )
        return {"updated_at": v.get("updated_at") or "", "messages": msgs}
    return {}


def read_profile_detailed() -> tuple[dict, bool]:
    exists = os.path.exists(PROFILE_META)
    meta = _read_json(PROFILE_META, {}) or {}
    return (
        {
            "memory_count": meta.get("count"),
            "refreshed_at": meta.get("at") or "",
        },
        exists,
    )


def read_profile() -> dict:
    return read_profile_detailed()[0]


def read_config() -> dict:
    return _read_json(PLUGIN_CFG, {}) or {}


def bot_running(timeout: float = 0.35) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", 6185))
        return True
    except Exception:
        return False
    finally:
        s.close()


def _strip_prefix(text: str, *prefixes: str) -> str:
    out = (text or "").strip()
    for p in prefixes:
        if out.startswith(p):
            return out[len(p):].strip()
    return out


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def human_gap(minutes: float) -> str:
    m = int(minutes)
    if m < 1:
        return "刚刚"
    if m < 60:
        return f"{m} 分钟"
    h, mm = divmod(m, 60)
    if h < 24:
        return f"{h} 小时 {mm} 分钟" if mm else f"{h} 小时"
    d, hh = divmod(h, 24)
    return f"{d} 天 {hh} 小时" if hh else f"{d} 天"


def build_snapshot() -> dict:
    now = datetime.now()
    warnings: list[str] = []
    conf = settings.load()
    if conf.get("_note"):
        warnings.append(conf["_note"])

    usable = is_root_usable()
    if not usable:
        warnings.insert(0, "还没有指定机器人数据目录（点右上角「设置路径」）")

    journal, jmeta = read_journal_detailed()
    cfg = read_config()
    prefs, pmeta = read_preferences_detailed()
    books = read_reading_all(prefs)
    reading = books[0] if books else {}
    chat = read_chat_tail(pref=prefs)
    profile, profile_exists = read_profile_detailed()
    running = bot_running()

    if usable and jmeta["missing"]:
        warnings.append(f"日记文件找不到：{JOURNAL}")
    if jmeta["bad_lines"]:
        warnings.append(f"有 {jmeta['bad_lines']} 行日记读不出来，已跳过（其余正常显示）")
    if usable and not pmeta["ok"]:
        if pmeta["missing"]:
            warnings.append(f"数据库文件找不到：{DB}")
        else:
            warnings.append("数据库暂时读不到（可能正被机器人写入），读书进度和最近对话这一轮为空")
    if usable and not profile_exists:
        warnings.append("记忆档案文件找不到：memory_profile 的统计暂时为空")

    # 最后一条“有动作”的痕迹（日记 + 数据库写入）
    marks = []
    for e in journal[:1]:
        if e["ts"]:
            marks.append(e["ts"])
    if reading.get("updated_at"):
        dt = parse_ts(reading["updated_at"])
        if dt:
            marks.append(dt.timestamp())
    if chat.get("updated_at"):
        dt = parse_ts(chat["updated_at"])
        if dt:
            marks.append(dt.timestamp())
    last_mark = max(marks) if marks else 0
    quiet = (now.timestamp() - last_mark) / 60 if last_mark else None

    # 状态推断：只看得到痕迹，说清楚是推断
    active_window = int(conf["active_minutes"]) * 60
    quiet_window = int(conf["quiet_minutes"])

    if not running:
        state = "没在运行"
        state_hint = "机器人进程没起来（6185 端口不通），下面显示的是它停之前留下的东西。"
    elif journal and journal[0]["ts"] and (now.timestamp() - journal[0]["ts"]) < active_window:
        last = journal[0]
        if last["kind"] == "read":
            state = "刚读了会儿书"
        elif last["kind"] == "message":
            state = "刚主动找过你"
        elif last["kind"] in ("self", "dialogue"):
            state = "刚写完日记"
        else:
            state = "刚记了一笔"
        state_hint = "从它自己留下的记录推出来的，不是实时状态。"
    elif quiet is not None and quiet < 90:
        state = "安静待着"
        state_hint = "没有新记录。它这个时间通常是在闲着的。"
    else:
        state = "很久没动静"
        state_hint = "长时间没有新记录，也可能只是没触发自主行动。"

    # 今天的统计
    today = now.strftime("%Y-%m-%d")
    todays = [e for e in journal if e["date"] == today]
    counts = {
        "journals": sum(1 for e in todays if e["kind"] in ("self", "dialogue")),
        "reads": sum(1 for e in todays if e["kind"] == "read"),
        "messages": sum(1 for e in todays if e["kind"] == "message"),
        "notes": len(todays),
    }

    from . import insight

    history = insight.same_day_history(journal, today)
    topic_list = insight.topics(journal)
    memory = insight.memory_profile()

    # 活动时间线：把日记里的动作摊平
    events = []
    for e in journal[: int(conf["timeline_limit"])]:
        kind = e["kind"]
        if kind == "read":
            title = "读了会儿书"
            detail = _strip_prefix(e["content"], "（自己读了会儿书）", "(自己读了会儿书)")
        elif kind == "message":
            title = "主动找你说话"
            detail = _strip_prefix(e["content"], "（我主动找他说）", "(我主动找他说)")
        elif kind == "autocapture":
            title = "自动补记"
            detail = _strip_prefix(e["content"], "（自动补记）", "(自动补记)")
        else:
            title = "写了一篇日记"
            detail = e["content"][:80]
        events.append(
            {
                "id": e["id"],
                "time": e["time"],
                "date": e["date"],
                "clock": e["clock"],
                "kind": kind,
                "label": KIND_META[kind]["label"],
                "title": title,
                "detail": detail[:120],
            }
        )

    return {
        "now": _fmt_dt(now),
        "bot": {
            "running": running,
            "state": state,
            "state_hint": state_hint,
            "quiet_minutes": round(quiet, 1) if quiet is not None else None,
            "quiet_text": human_gap(quiet) if quiet is not None else "—",
            "last_mark": _fmt_dt(datetime.fromtimestamp(last_mark)) if last_mark else "",
        },
        "reading": {
            "book": reading.get("book", ""),
            "pos": reading.get("pos", 0),
            "total": reading.get("total", 0),
            "percent": reading.get("percent", 0),
            "updated_at": reading.get("updated_at", ""),
        },
        "books": books,
        "settings": {k: v for k, v in conf.items() if not k.startswith("_")},
        "chat": chat,
        "profile": profile,
        "history": history,
        "topics": topic_list,
        "memory": memory,
        "today": counts,
        "events": events,
        "journal": journal,
        "autonomy": {
            "enabled": bool(cfg.get("autonomy_enable", True)),
            "interval": cfg.get("autonomy_interval_min", 20),
            "start": cfg.get("autonomy_start_hour", 8),
            "end": cfg.get("autonomy_end_hour", 23),
        },
        "source": {
            "journal": JOURNAL,
            "journal_mtime": _fmt_dt(datetime.fromtimestamp(os.stat(JOURNAL).st_mtime))
            if os.path.exists(JOURNAL)
            else "",
        },
        "warnings": warnings,
        "journal_meta": jmeta,
        "setup": {
            "needed": not usable,
            "bot_root": BOT_ROOT,
            "source": ROOT_SOURCE,
            "default": DEFAULT_BOT_ROOT,
        },
    }
