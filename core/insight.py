"""从日记里做一点本地统计：往年今天、常提到的词、记忆档案。

全部是纯本地字符串处理，不联网、不调用任何模型、不写回机器人。
中文分词用内置的 jieba（纯 Python，随程序自带）；万一不可用，退回词频统计。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections import Counter

from . import data as botdata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
VENDOR = os.path.join(BASE, "vendor")
WORDS_FILE = os.path.join(DATA_DIR, "words.txt")

FIXED_WORDS = ["子漾", "润子漾", "大肥鱼", "浩宇", "李浩宇", "长日将尽", "QQ空间", "语音", "日记本"]

STOP_WORDS = {
    "自己", "什么", "这个", "那个", "我们", "你们", "他们", "没有", "就是", "可以",
    "因为", "所以", "但是", "时候", "现在", "已经", "还是", "这样", "那样", "知道",
    "觉得", "事情", "东西", "一下", "有点", "不是", "真的", "其实", "然后", "而且",
    "如果", "虽然", "不过", "于是", "起来", "出来", "进来", "下来", "上来", "一样",
    "一点", "有些", "这里", "那里", "哪里", "怎么", "为什么", "多少", "这些", "那些",
    "以后", "以前", "之后", "之前", "当时", "刚刚", "马上", "一直", "总是", "好像",
    "可能", "应该", "需要", "今天", "昨天", "明天", "晚上", "早上", "时间", "感觉",
    "时候", "地方", "有点", "不太", "只是", "还有", "一些", "这种", "那种", "反正",
}

STOP_CHARS = set("的了着过是在有和与就都也还很太不没我你他她它们这那哪个一上下中来回说要想会能可被把对从到而为以于之其所以因为但是如果")

_jieba = None


def _custom_words() -> list[str]:
    words = list(FIXED_WORDS)
    try:
        for name in os.listdir(botdata.BOOKS_DIR):
            stem = os.path.splitext(name)[0]
            if stem:
                words.append(stem)
    except OSError:
        pass
    try:
        with open(WORDS_FILE, "r", encoding="utf-8-sig") as f:
            for line in f:
                w = line.strip()
                if w and not w.startswith("#"):
                    words.append(w)
    except OSError:
        pass
    return words


def _get_jieba():
    """懒加载分词器；缓存文件放在本程序自己的 data 目录。"""
    global _jieba
    if _jieba is not None:
        return _jieba or None
    try:
        if VENDOR not in sys.path:
            sys.path.insert(0, VENDOR)
        import warnings

        with warnings.catch_warnings():
            # jieba 里几个正则没写 raw 字符串，Python 3.12 会刷一堆 SyntaxWarning
            warnings.simplefilter("ignore", SyntaxWarning)
            import jieba  # noqa: WPS433

        os.makedirs(DATA_DIR, exist_ok=True)
        jieba.dt.tmp_dir = DATA_DIR
        jieba.dt.cache_file = os.path.join(DATA_DIR, "jieba.cache")
        for w in _custom_words():
            jieba.add_word(w)
        jieba.initialize()
        _jieba = jieba
        return jieba
    except Exception:
        _jieba = False
        return None


def same_day_history(journal: list[dict], today: str, limit: int = 8) -> list[dict]:
    """往年同一天写过什么（月-日相同、年份不同）。"""
    md = today[5:]
    year = today[:4]
    hits = [e for e in journal if e["date"][5:] == md and e["date"][:4] != year]
    hits.sort(key=lambda e: e["ts"], reverse=True)
    return hits[:limit]


def _topics_with_jieba(journal: list[dict], jieba, limit: int) -> list[dict]:
    texts = [e["content"] for e in journal if e["kind"] in ("self", "dialogue")]
    if len(texts) < 3:
        return []
    counter: Counter = Counter()
    doc_freq: Counter = Counter()
    for text in texts:
        tokens = set()
        for tok in jieba.cut(text):
            tok = tok.strip()
            if len(tok) < 2 or tok in STOP_WORDS:
                continue
            if not re.search(r"[\u4e00-\u9fff]", tok):
                continue
            if any(ch in STOP_CHARS for ch in tok):
                continue
            counter[tok] += 1
            tokens.add(tok)
        for tok in tokens:
            doc_freq[tok] += 1

    cands = [(w, c, doc_freq[w]) for w, c in counter.items() if doc_freq[w] >= 2 and c >= 2]
    cands.sort(key=lambda x: (x[2], len(x[0]), x[1]), reverse=True)
    return [{"word": w, "count": c, "entries": d} for w, c, d in cands[:limit]]


def _topics_with_ngram(journal: list[dict], limit: int) -> list[dict]:
    """没有分词器时的兜底：2~4 字词频 + 双篇出现过滤。"""
    texts = [e["content"] for e in journal if e["kind"] in ("self", "dialogue")]
    if len(texts) < 3:
        return []
    segments = []
    for t in texts:
        segments.extend(s for s in re.split(r"[^\u4e00-\u9fff]+", t) if s)
    total = sum(len(s) for s in segments)
    if total < 60:
        return []
    min_count = 3 if total > 1500 else 2
    counter: Counter = Counter()
    doc_freq: Counter = Counter()
    for entry in texts:
        seen = set()
        for seg in re.split(r"[^\u4e00-\u9fff]+", entry):
            for n in (2, 3, 4):
                for i in range(len(seg) - n + 1):
                    w = seg[i:i + n]
                    counter[w] += 1
                    seen.add(w)
        for w in seen:
            doc_freq[w] += 1
    cands = []
    for word, count in counter.items():
        if count < min_count or doc_freq[word] < 2:
            continue
        if word in STOP_WORDS or any(ch in STOP_CHARS for ch in word):
            continue
        cands.append((word, count, doc_freq[word]))
    cands.sort(key=lambda x: (x[2], len(x[0]), x[1]), reverse=True)
    chosen = []
    for word, count, df in cands:
        if any(word in longer and ldf >= df * 0.7 for longer, _, ldf in chosen):
            continue
        chosen.append((word, count, df))
        if len(chosen) >= limit:
            break
    return [{"word": w, "count": c, "entries": d} for w, c, d in chosen]


def topics(journal: list[dict], limit: int = 12) -> list[dict]:
    """常提到的 2 字以上词，按「出现在多少篇」排序。"""
    jieba = _get_jieba()
    if jieba is not None:
        try:
            return _topics_with_jieba(journal, jieba, limit)
        except Exception:
            pass
    return _topics_with_ngram(journal, limit)


def memory_profile() -> dict:
    """记忆档案（它自动整理的那份），只读展示。"""
    path = botdata.PROFILE_META.replace("profile_meta.json", "memory_profile.md")
    out = {"exists": os.path.exists(path), "path": path, "sections": [], "chars": 0, "updated_at": ""}
    if not out["exists"]:
        return out
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError:
        out["exists"] = False
        return out

    out["chars"] = len(text)
    try:
        import time as _t

        st = os.stat(path)
        out["updated_at"] = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(st.st_mtime))
    except OSError:
        pass

    sections = []
    current = {"title": "开头", "lines": []}
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"^【(.+?)】$", line.strip())
        if m:
            if current["lines"]:
                sections.append(current)
            current = {"title": m.group(1), "lines": []}
        elif line.strip():
            text_line = line.strip()
            text_line = re.sub(r"^[-•·*]\s*", "", text_line)
            current["lines"].append(text_line)
    if current["lines"]:
        sections.append(current)
    out["sections"] = sections
    return out


# ---------------- 记忆：最近几天 / 短期 / 长期（只读） ----------------

def _neg_time(text: str) -> float:
    """把 '2026-10-29 20:29' 变成可倒序的负数；解析不了算最早。"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return -time.mktime(time.strptime(text.strip(), fmt))
        except (ValueError, AttributeError):
            continue
    return 0.0

def _data_dir() -> str:
    return os.path.dirname(botdata.PROFILE_META)


def _qbot_dir() -> str:
    """qbot 根目录（备份、日志都在这下面）。测试可用 ZZYANG_QBOT 覆盖。"""
    override = os.environ.get("ZZYANG_QBOT")
    if override:
        return override
    return os.path.dirname(os.path.dirname(os.path.dirname(botdata.BOT_ROOT)))


def _backup_dir() -> str:
    return os.path.join(_qbot_dir(), "backup", "daily")


def _backup_log() -> str:
    return os.path.join(_qbot_dir(), "tools", "backup.log")


def _watchdog_log() -> str:
    return os.path.join(_qbot_dir(), "tools", "watchdog.log")


def _fallback_key() -> str:
    return os.path.join(_data_dir(), "fallback_key.txt")


def _mtime_text(path: str) -> str:
    try:
        st = os.stat(path)
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
    except OSError:
        return ""


def read_profile_recent() -> dict:
    """最近几天（profile_recent.md），每天 21:30 刷新。"""
    path = os.path.join(_data_dir(), "profile_recent.md")
    out = {"exists": os.path.exists(path), "path": path, "lines": [], "chars": 0,
           "updated_at": "", "updated_day": ""}
    if not out["exists"]:
        return out
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError:
        out["exists"] = False
        return out
    out["chars"] = len(text)
    out["updated_at"] = _mtime_text(path)
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^（更新于\s*(.+?)）$", line)
        if m:
            out["updated_day"] = m.group(1)
            continue
        out["lines"].append(line.lstrip("- ").strip())
    return out


def read_short_memory() -> dict:
    """短期记忆：池 / 暂存 / 回收站。"""
    path = os.path.join(_data_dir(), "short_memory.json")
    out = {"exists": os.path.exists(path), "path": path, "counts": {}, "items": [],
           "updated_at": "", "total": 0}
    if not out["exists"]:
        return out
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = json.load(f)
    except Exception:
        out["exists"] = False
        return out
    out["updated_at"] = _mtime_text(path)
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        items = []
    now = time.time()
    counts = {"pool": 0, "temp": 0, "trash": 0}
    # 插件的状态词：pool（池）→ hold（暂存）→ trash（回收站）。
    # 早期文档写的是 temp，实际实现用的是 hold，这里统一。
    STATUS_ALIAS = {"hold": "temp", "temp": "temp", "pool": "pool", "trash": "trash"}
    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        raw_status = str(it.get("status") or "pool").strip().lower()
        status = STATUS_ALIAS.get(raw_status, raw_status)
        counts[status] = counts.get(status, 0) + 1
        days_left = None
        try:
            # 暂存看 hold_until，回收站看 trash_until（新字段）
            deadline = it.get("hold_until") if status == "temp" else it.get("trash_until")
            deadline = float(deadline or 0)
            if deadline > 0:
                days_left = max(0, math.ceil((deadline - now) / 86400))
        except (TypeError, ValueError):
            pass

        rows.append({
            "content": str(it.get("content") or "").strip(),
            "reply": str(it.get("reply") or "").strip()[:160],
            "created": str(it.get("created") or ""),
            "hits": int(it.get("hits") or 0),
            "survived": int(it.get("survived") or 0),
            "status": status,
            "days_left": days_left,
            # 新字段：豁免（不参与每晚重判）与被保留的日期
            "exempt": bool(it.get("exempt")),
            "kept_on": str(it.get("kept_on") or "")[:10],
        })
    order = {"pool": 0, "temp": 1, "trash": 2}
    rows.sort(key=lambda r: (order.get(r["status"], 9), "" if r["created"] else "", r["created"]))
    rows.sort(key=lambda r: (order.get(r["status"], 9), _neg_time(r["created"])))
    out["counts"] = counts
    out["total"] = len(rows)
    out["items"] = rows
    return out


def _epoch_text(value) -> str:
    """长期记忆的时间可能是毫秒时间戳，转成 2026-10-29 20:29。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.isdigit():
        try:
            seconds = float(text) / 1000.0 if len(text) > 11 else float(text)
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(seconds))
        except (ValueError, OSError):
            return text
    return text


def read_long_memory(limit_recent: int = 40, limit_top: int = 8) -> dict:
    """长期记忆：只给分布 + 最近若干条 + 被想起最多的几条。"""
    folder = os.path.join(_data_dir(), "long_memory")
    out = {"exists": os.path.isdir(folder), "path": folder, "total": 0, "kinds": {},
           "recent": [], "top": [], "updated_at": "", "files": 0,
           "layers": {}, "raw_times": []}
    if not out["exists"]:
        return out
    names = []
    try:
        names = [n for n in os.listdir(folder) if n.lower().endswith(".json")]
    except OSError:
        return out
    out["files"] = len(names)
    rows = []
    raw_times = []
    for name in names:
        p = os.path.join(folder, name)
        try:
            with open(p, "r", encoding="utf-8-sig", errors="replace") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, dict):
            data = data.get("items") or data.get("memories") or []
        if not isinstance(data, list):
            continue
        for it in data:
            if not isinstance(it, dict):
                continue
            content = str(it.get("content") or "").strip()
            if not content:
                continue
            kind = str(it.get("kind") or "chat")
            layer = str(it.get("layer") or "raw")
            if layer == "raw":
                try:
                    raw_times.append(int(it.get("createTime") or 0))
                except Exception:
                    pass
            rows.append({
                "content": content,
                "kind": kind,
                "layer": layer,
                "created": _epoch_text(it.get("created") or it.get("createTime")),
                "hits": int(it.get("hits") or 0),
            })
        if not out["updated_at"]:
            out["updated_at"] = _mtime_text(p)
    out["total"] = len(rows)
    kinds: dict = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    out["kinds"] = kinds
    layers: dict = {}
    for r in rows:
        layers[r["layer"]] = layers.get(r["layer"], 0) + 1
    out["layers"] = layers
    out["raw_times"] = raw_times
    by_time = sorted(rows, key=lambda r: r["created"], reverse=True)
    out["recent"] = by_time[:limit_recent]
    out["top"] = sorted(rows, key=lambda r: r["hits"], reverse=True)[:limit_top]
    return out

def read_long_memory_page(offset: int = 0, limit: int = 50, layer: str = "") -> dict:
    """翻页看全部长期记忆（只读主人目录，不含好友/群）。"""
    folder = os.path.join(_data_dir(), "long_memory")
    rows = []
    if os.path.isdir(folder):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            names = []
        for name in names:
            if not name.lower().endswith(".json"):
                continue
            p = os.path.join(folder, name)
            try:
                with open(p, "r", encoding="utf-8-sig", errors="replace") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for it in data:
                if not isinstance(it, dict):
                    continue
                c = str(it.get("content") or "").strip()
                if not c:
                    continue
                rows.append({
                    "content": c,
                    "layer": str(it.get("layer") or "raw"),
                    "kind": str(it.get("kind") or "chat"),
                    "created": _epoch_text(it.get("createTime") or it.get("created")),
                    "hits": int(it.get("hits") or 0),
                })
    if layer:
        rows = [r for r in rows if r["layer"] == layer]
    rows.sort(key=lambda r: r["created"], reverse=True)
    off = max(0, int(offset or 0))
    lim = max(1, min(200, int(limit or 50)))
    return {"total": len(rows), "offset": off, "limit": lim, "items": rows[off:off + lim]}

def read_friend_memory(limit: int = 20) -> dict:
    """好友 / 群的记忆：分区后放在 long_memory/guests 与 long_memory/groups。

    单独成一块，是为了不跟主人自己的记忆混在同一个列表里——
    以前所有 json 都在 long_memory 根目录，扫一遍就全混在一起了。
    """
    base = os.path.join(_data_dir(), "long_memory")
    out = {"exists": False, "total": 0, "people": 0, "items": []}
    rows = []
    files = 0
    for sub in ("guests", "groups"):
        folder = os.path.join(base, sub)
        if not os.path.isdir(folder):
            continue
        out["exists"] = True
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(".json"):
                continue
            p = os.path.join(folder, name)
            try:
                with open(p, "r", encoding="utf-8-sig", errors="replace") as f:
                    data = json.load(f)
            except Exception:
                continue
            if isinstance(data, dict):
                data = data.get("items") or data.get("memories") or []
            if not isinstance(data, list):
                continue
            files += 1
            who = name[:-5]
            for it in data:
                if not isinstance(it, dict):
                    continue
                content = str(it.get("content") or "").strip()
                if not content:
                    continue
                rows.append({
                    "who": who,
                    "sub": sub,
                    "content": content,
                    "created": _epoch_text(it.get("created") or it.get("createTime")),
                })
    out["people"] = files
    out["total"] = len(rows)
    rows.sort(key=lambda r: r["created"], reverse=True)
    out["items"] = rows[:limit]
    return out

def read_guest_profiles(limit: int = 20) -> list[dict]:
    """好友档案：每人一份不超过 500 字的客观印象。"""
    folder = os.path.join(_data_dir(), "guest_profile")
    out = []
    if not os.path.isdir(folder):
        return out
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".md"))
    except OSError:
        return out
    for name in names[:limit]:
        p = os.path.join(folder, name)
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        out.append({
            "uid": name[:-3],
            "chars": len(text.strip()),
            "updated_at": _mtime_text(p),
            "preview": text.strip()[:80],
        })
    return out

def memory_health(short: dict, recent: dict, long_mem: dict, journal: list) -> dict:
    """记忆健康：整理、档案、短期池、长期增长，外加备份与看护。只读推断。"""
    now = time.localtime()
    today = time.strftime("%Y-%m-%d", now)
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    after_curation = (now.tm_hour, now.tm_min) >= (22, 30)

    # 每晚 22:30 自审：最后一次整理的日子
    last_day = ""
    try:
        with open(short.get("path", ""), "r", encoding="utf-8-sig", errors="replace") as f:
            last_day = str(json.load(f).get("last_curation_day") or "")
    except Exception:
        last_day = ""

    if not last_day:
        curation_missed = after_curation
        curation_note = "还没记录过整理时间"
    elif last_day < yesterday:
        curation_missed = True
        curation_note = f"已经 {_days_between(last_day, today)} 天没有整理"
    elif last_day == yesterday and after_curation:
        curation_missed = True
        curation_note = "今天 22:30 的整理还没跑"
    else:
        curation_missed = False
        curation_note = "按时整理"

    # 最近几天档案：每天 21:30
    recent_age_h = None
    if recent.get("path") and os.path.exists(recent["path"]):
        recent_age_h = round((time.time() - os.path.getmtime(recent["path"])) / 3600, 1)
    recent_stale = recent_age_h is not None and recent_age_h > 26

    # 长期底色：超过 6 天才该重写
    prof_age_d = None
    path = os.path.join(_data_dir(), "memory_profile.md")
    if os.path.exists(path):
        prof_age_d = round((time.time() - os.path.getmtime(path)) / 86400, 1)

    counts = short.get("counts") or {}
    pool = int(counts.get("pool") or 0)
    items = short.get("items") or []
    oldest = 0
    for it in items:
        if it.get("created"):
            oldest = max(oldest, _days_between(it["created"][:10], today))

    trash = int(counts.get("trash") or 0)
    # 回收站过期：有 trash_until 就看它，没有才退回 created+7 天
    trash_stuck = False
    for it in items:
        if it.get("status") != "trash":
            continue
        left = it.get("days_left")
        if left is not None:
            if left <= 0:
                trash_stuck = True
                break
        elif it.get("created") and _days_between(it["created"][:10], today) > 7:
            trash_stuck = True
            break

    # 今天保留了几条（插件每天最多留 daily_keep_max 条）
    kept_today = sum(1 for it in items if it.get("kept_on") == today)
    exempt_count = sum(1 for it in items if it.get("exempt"))
    keep_max = 10

    today_entries = sum(1 for e in journal if e.get("date") == today)

    return {
        "curation": {"last_day": last_day, "missed": curation_missed, "note": curation_note},
        "recent": {"age_hours": recent_age_h, "stale": recent_stale},
        "profile": {"age_days": prof_age_d, "stale": bool(prof_age_d is not None and prof_age_d > 6)},
        "short": {"pool": pool, "temp": int(counts.get("temp") or 0), "trash": trash,
                  "oldest_days": oldest, "crowded": pool > 150, "trash_stuck": trash_stuck},
        "keep": {"today": kept_today, "max": keep_max, "at_limit": kept_today >= keep_max,
                 "exempt": exempt_count},
        "backup": _backup_health(),
        "watchdog": _watchdog_health(),
        "fallback": {"exists": os.path.isfile(_fallback_key())},
        "long": {"total": int(long_mem.get("total") or 0),
                 "newest": (long_mem.get("recent") or [{}])[0].get("created", "")},
        "journal": {"today": today_entries},
    }


def _backup_health() -> dict:
    """每日备份：看备份目录里最新的 zip 和它的年龄。只看文件名/大小/时间，不打开。"""
    out = {"exists": False, "count": 0, "latest": "", "updated_at": "", "age_hours": None,
           "size_mb": None, "stale": False}
    folder = _backup_dir()
    try:
        names = [n for n in os.listdir(folder) if n.lower().endswith(".zip")]
    except OSError:
        return out
    out["exists"] = True
    out["count"] = len(names)
    if not names:
        return out
    latest = max(names)
    full = os.path.join(folder, latest)
    try:
        st = os.stat(full)
        out["latest"] = latest
        out["updated_at"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
        out["age_hours"] = round((time.time() - st.st_mtime) / 3600, 1)
        out["size_mb"] = round(st.st_size / 1024 / 1024, 1)
        out["stale"] = out["age_hours"] > 30
    except OSError:
        pass
    return out


def _watchdog_health() -> dict:
    """看护任务：读 watchdog.log 最后一条 restarted 的时间。只读日志尾部。"""
    out = {"exists": False, "last": "", "minutes_since": None, "restarts_today": 0}
    log = _watchdog_log()
    if not os.path.exists(log):
        return out
    out["exists"] = True
    today = time.strftime("%Y-%m-%d")
    last_ts = None
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]
    except OSError:
        return out
    for line in lines:
        text = line.strip()
        if not text:
            continue
        stamp = text.split(" ")[0]
        if stamp.startswith(today):
            out["restarts_today"] += 1
        try:
            last_ts = stamp
        except Exception:
            pass
    if last_ts:
        out["last"] = last_ts.replace("T", " ")[:16]
        try:
            dt = time.mktime(time.strptime(last_ts[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S"))
            out["minutes_since"] = int((time.time() - dt) / 60)
        except (ValueError, TypeError):
            pass
    return out


def _days_between(day: str, today: str) -> int:
    try:
        a = time.mktime(time.strptime(day[:10], "%Y-%m-%d"))
        b = time.mktime(time.strptime(today[:10], "%Y-%m-%d"))
        return int(round((b - a) / 86400))
    except (ValueError, TypeError):
        return 0
