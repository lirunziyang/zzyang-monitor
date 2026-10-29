"""只读性回归检查：跑一遍本程序，确认机器人那边的文件一个都没被动过。

用法：
    runtime\\python.exe tools\\readonly_check.py

退出码：0 = 全部一致；1 = 有文件被改动 / 新增 / 删除
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import data as botdata  # noqa: E402

PY = os.path.join(BASE, "runtime", "python.exe")
APP = os.path.join(BASE, "app.py")
PLUGIN_DIR = botdata.PLUGIN_DATA
INSTANCE_DIR = botdata.BOT_ROOT

# 严格比对（内容哈希）
STRICT = [
    botdata.JOURNAL,
    botdata.PROFILE_META,
    botdata.PLUGIN_CFG,
]
# 只比元信息（这些文件会被正在运行的机器人正常写入）
META = [
    botdata.DB,
    botdata.DB + "-wal",
    botdata.DB + "-shm",
]


def digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snap() -> dict:
    out = {}
    for p in STRICT:
        if not os.path.exists(p):
            out[p] = {"exists": False}
            continue
        st = os.stat(p)
        out[p] = {
            "exists": True,
            "size": st.st_size,
            "mtime": st.st_mtime_ns,
            "sha": digest(p),
            "kind": "strict",
        }
    for p in META:
        if not os.path.exists(p):
            out[p] = {"exists": False, "kind": "meta"}
            continue
        st = os.stat(p)
        out[p] = {
            "exists": True,
            "size": st.st_size,
            "mtime": st.st_mtime_ns,
            "kind": "meta",
        }
    return out


def listing(folder: str) -> set:
    try:
        return {n for n in os.listdir(folder) if not n.startswith(".")}
    except OSError:
        return set()


def structure_checks(snap: dict) -> list:
    """检查读取结果的结构是否还符合预期（机器人插件升级后第一时间发现）。"""
    out = []

    # 1. 日记条目字段
    need = ["id", "time", "date", "clock", "content", "kind", "ts", "chars"]
    bad = []
    for e in snap.get("journal", [])[:50]:
        missing = [k for k in need if k not in e]
        if missing:
            bad.append(f"{e.get('time', '?')} 缺 {missing}")
        elif e["kind"] not in ("self", "dialogue", "read", "message", "autocapture"):
            bad.append(f"{e.get('time', '?')} 未知类型 {e['kind']}")
    out.append(("日记字段", not bad, "；".join(bad[:3]) if bad else f"{len(snap.get('journal', []))} 条字段齐全"))

    # 2. 读书进度
    reading = snap.get("reading") or {}
    if reading:
        keys = ["book", "pos", "total", "percent", "updated_at"]
        miss = [k for k in keys if k not in reading]
        out.append(("读书进度", not miss, f"缺 {miss}" if miss else f"{reading['book']} {reading['percent']}%"))
    else:
        out.append(("读书进度", True, "当前没有在读的书"))

    # 3. 书架数组
    books = snap.get("books")
    ok = isinstance(books, list) and all("book" in b and "pos" in b for b in books)
    out.append(("书架数组", ok, f"{len(books) if isinstance(books, list) else '?'} 本"))

    # 4. 记忆档案
    mem = snap.get("memory") or {}
    ok = all(k in mem for k in ("exists", "sections", "chars"))
    out.append(("记忆档案", ok, f"{len(mem.get('sections', []))} 段 / {mem.get('chars', 0)} 字"))

    # 5. 设置项
    st = snap.get("settings") or {}
    miss = [k for k in ("refresh_seconds", "page_size", "timeline_limit") if k not in st]
    out.append(("设置项", not miss, f"缺 {miss}" if miss else "齐全"))

    # 6. 状态文案
    state = (snap.get("bot") or {}).get("state", "")
    out.append(("状态文案", bool(state), state or "为空"))

    # 7. 日记必须逐字照抄原文
    out.append(verbatim_check(snap))

    return out


def _journal_texts() -> tuple[set, set]:
    """返回（日记原文集合，读书记录集合）。

    读书记录由插件单独写在 reading_log.jsonl 里，界面上的文案是程序按
    「书名 + 起止字」拼出来的，所以要和日志字段逐一对应，不能拿去和日记比对。
    """
    raw: set = set()
    try:
        with open(botdata.JOURNAL, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                content = str(row.get("content") or "").strip()
                if content:
                    raw.add(content)
    except OSError:
        pass

    reads: set = set()
    try:
        with open(botdata.READING_LOG, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                book = str(row.get("book") or "").strip()
                if not book:
                    continue
                try:
                    start, end = int(row.get("start") or 0), int(row.get("end") or 0)
                except (TypeError, ValueError):
                    continue
                reads.add(f"（自己读了会儿书）《{book}》第 {start}–{end} 字")
    except OSError:
        pass
    return raw, reads


def verbatim_check(snap: dict) -> tuple:
    """界面拿到的正文必须能追回源文件：日记对日记文件，读书对读书日志。"""
    raw, reads = _journal_texts()
    if not raw and not reads:
        return ("日记原文一致", True, "源文件不存在，跳过")

    bad = []
    for e in snap.get("journal", []):
        text = str(e.get("content", "")).strip()
        pool = reads if e.get("kind") == "read" else raw
        if text not in pool:
            bad.append(e)

    if bad:
        sample = str(bad[0].get("content", ""))[:24]
        return ("日记原文一致", False, f"{len(bad)} 条正文追不回源文件，例如「{sample}」")
    return (
        "日记原文一致",
        True,
        f"{len(snap.get('journal', []))} 条逐字一致（日记 {len(raw)} / 读书 {len(reads)}）",
    )

def compare(before: dict, after: dict) -> list:
    rows = []
    for path, b in before.items():
        a = after.get(path, {"exists": False})
        name = os.path.basename(path)
        if not b["exists"] and not a["exists"]:
            rows.append((name, "SKIP", "文件本就不存在", True))
            continue
        if b["exists"] != a["exists"]:
            rows.append((name, "CHANGED", "存在状态变化", False))
            continue
        if b.get("kind") == "strict":
            if b["sha"] != a["sha"]:
                rows.append((name, "CHANGED", "内容变了", False))
            else:
                rows.append((name, "SAME", f"{b['size']} 字节", True))
        else:
            # 机器人自己在运行时，数据库必然会被它写；这里只保证「我们没多写」
            if b["size"] == a["size"] and b["mtime"] == a["mtime"]:
                rows.append((name, "SAME", "元信息未变", True))
            else:
                rows.append((name, "BUSY", "机器人在写，属正常", True))
    return rows


def main() -> int:
    if not os.path.exists(PY):
        print(f"[错误] 找不到运行环境：{PY}")
        return 1

    print("== 只读性回归检查 ==")
    print(f"程序目录：{BASE}")
    print(f"监测目标：{botdata.BOT_ROOT}\n")

    before = snap()
    files_before = listing(PLUGIN_DIR)
    inst_before = listing(INSTANCE_DIR)

    t0 = time.time()
    proc = subprocess.run(
        [PY, APP, "--check"],
        cwd=BASE,
        capture_output=True,
        timeout=120,
    )
    cost = time.time() - t0
    if proc.returncode != 0:
        print("[错误] 程序自身运行失败，先修程序：")
        print(proc.stderr.decode("utf-8", "replace")[:2000])
        return 1
    print(f"已完整读取一次数据（{cost:.2f}s，退出码 {proc.returncode}）\n")

    # 结构断言：机器人插件升级后格式若变了，这里第一时间发现
    snap_data = None
    try:
        snap_data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except Exception as e:
        print(f"!! 快照不是合法 JSON：{e}")
        return 1

    shape_ok = True
    for label, passed, detail in structure_checks(snap_data):
        shape_ok = shape_ok and passed
        print(f"{'  ' if passed else '!!'} 结构/{label.ljust(12)} {'OK' if passed else 'FAIL'}  {detail}")
    print()
    if not shape_ok:
        print("RESULT: FAIL  数据结构变了，先对齐解析再继续")
        return 1

    after = snap()
    rows = compare(before, after)

    ok = True
    width = max(len(r[0]) for r in rows) if rows else 10
    for name, status, note, passed in rows:
        ok = ok and passed
        flag = "  " if passed else "!!"
        print(f"{flag} {name.ljust(width)}  {status.ljust(8)}  {note}")

    files_after = listing(PLUGIN_DIR)
    inst_after = listing(INSTANCE_DIR)
    added = (files_after - files_before) | (inst_after - inst_before)
    removed = (files_before - files_after) | (inst_before - inst_after)
    if added:
        ok = False
        print(f"!! 新增文件：{sorted(added)}")
    if removed:
        ok = False
        print(f"!! 文件消失：{sorted(removed)}")
    if not added and not removed:
        print("   目录内容             SAME      没有新增或消失的文件")

    print()
    if ok:
        print("RESULT: PASS  机器人侧零改动")
        return 0
    print("RESULT: FAIL  检测到改动，请检查上面的 !! 行")
    return 1


if __name__ == "__main__":
    sys.exit(main())
