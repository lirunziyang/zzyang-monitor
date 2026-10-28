"""从日记里做一点本地统计：往年今天、常提到的词、记忆档案。

全部是纯本地字符串处理，不联网、不调用任何模型、不写回机器人。
中文分词用内置的 jieba（纯 Python，随程序自带）；万一不可用，退回词频统计。
"""
from __future__ import annotations

import os
import re
import sys
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
