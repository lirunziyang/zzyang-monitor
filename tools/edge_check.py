"""边界用例：在临时目录里造数据，验证异常态不会白屏、不会崩。

这些用例**只操作临时副本**，通过 ZZYANG_DATA_ROOT 指过去，
不会碰 D:\\dshword 里的真实文件。

用法：
    runtime\\python.exe tools\\edge_check.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(BASE, "runtime", "python.exe")
APP = os.path.join(BASE, "app.py")
TMP = os.path.join(BASE, "tests", ".tmp")

RESULTS = []


def build_root(name: str) -> str:
    root = os.path.join(TMP, name)
    if os.path.exists(root):
        shutil.rmtree(root, ignore_errors=True)
    for sub in (
        "plugins/astrbot_plugin_edge_tts/data/books",
        "config",
    ):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


def write_journal(root: str, lines: list[str]) -> None:
    path = os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/journal.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_profile(root: str, count: int = 12) -> None:
    path = os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/profile_meta.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"count": count, "ts": 1.0, "at": "2026-10-27 21:30"}, f)


def write_book(root: str, name: str = "测试书.txt", chars: int = 1000) -> None:
    path = os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/books", name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("字" * chars)


def write_config(root: str) -> None:
    path = os.path.join(root, "config/astrbot_plugin_edge_tts_config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"autonomy_enable": True, "autonomy_interval_min": 20}, f)


def write_db(root: str, pos: int = 250) -> None:
    path = os.path.join(root, "data_v4.db")
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE preferences (created_at TEXT, updated_at TEXT, id INTEGER PRIMARY KEY, "
        "scope TEXT, scope_id TEXT, key TEXT, value TEXT)"
    )
    con.execute(
        "INSERT INTO preferences (created_at, updated_at, scope, scope_id, key, value) "
        "VALUES ('2026-10-27 10:00','2026-10-27 10:00','plugin','p','astrbot_plugin_edge_tts:book_pos:测试书.txt', ?)",
        (json.dumps({"val": pos}),),
    )
    con.execute(
        "INSERT INTO preferences (created_at, updated_at, scope, scope_id, key, value) "
        "VALUES ('2026-10-27 10:05','2026-10-27 10:05','plugin','p',"
        "'astrbot_plugin_edge_tts:chat_log:private:1', ?)",
        (json.dumps({"val": [{"role": "user", "content": "在吗"}, {"role": "assistant", "content": "在的"}]}),),
    )
    con.commit()
    con.close()


def run_snapshot(root: str) -> dict:
    env = dict(os.environ)
    env["ZZYANG_DATA_ROOT"] = root
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([PY, APP, "--check"], cwd=BASE, capture_output=True, timeout=120, env=env)
    if proc.returncode != 0:
        raise RuntimeError("程序退出码 " + str(proc.returncode) + "：" + proc.stderr.decode("utf-8", "replace")[:800])
    return json.loads(proc.stdout.decode("utf-8", "replace"))


def case(name: str, fn):
    try:
        detail = fn()
        RESULTS.append((name, True, detail))
    except Exception as e:
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))


def assert_(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------- 用例 ----------------

def case_normal():
    root = build_root("normal")
    write_journal(
        root,
        [
            '{"time":"2026-10-27 22:56","content":"今晚他说的那件事，我一直在想。","auto":true}',
            '{"time":"2026-10-27 12:22","content":"今天小宇说，记忆只会被压缩。","auto":false}',
            '{"time":"2026-10-27 12:22","content":"今天小宇说，记忆只会被压缩。","auto":false}',
            '{"time":"2026-10-27 21:55","content":"（自己读了会儿书）《测试书.txt》第 0–1000 字，共 1000 字。","auto":true}',
        ],
    )
    write_profile(root)
    write_book(root)
    write_config(root)
    write_db(root)
    snap = run_snapshot(root)
    assert_(len(snap["journal"]) == 3, f"重复条目应合并，实际 {len(snap['journal'])} 条")
    dup = [e for e in snap["journal"] if e["duplicates"] == 2]
    assert_(len(dup) == 1, "应识别出 1 条重复")
    assert_(snap["reading"]["total"] == 1000, "书籍总字数不对")
    assert_(snap["reading"]["percent"] == 25.0, "读书百分比不对")
    assert_(not snap["warnings"], f"正常数据不该有警告：{snap['warnings']}")
    kinds = {e["kind"] for e in snap["journal"]}
    assert_({"self", "dialogue", "read"} <= kinds, f"分类不对：{kinds}")
    return "3 条记录、1 条重复合并、读书 25.0%、无警告"


def case_missing_journal():
    root = build_root("missing_journal")
    write_profile(root)
    write_config(root)
    write_db(root)
    snap = run_snapshot(root)
    assert_(snap["journal"] == [], "日记应为空")
    assert_(any("日记文件找不到" in w for w in snap["warnings"]), f"缺少提示：{snap['warnings']}")
    assert_(snap["bot"]["state"], "状态文案不能为空")
    return "空日记 + 明确提示 + 状态文案正常"


def case_bad_line():
    root = build_root("bad_line")
    write_journal(
        root,
        [
            '{"time":"2026-10-27 22:56","content":"正常的一条","auto":true}',
            '{"time":"2026-10-27 23:00","content": 坏掉的 JSON',
        ],
    )
    write_profile(root)
    write_config(root)
    write_db(root)
    snap = run_snapshot(root)
    assert_(len(snap["journal"]) == 1, "坏行应被跳过，保留 1 条")
    assert_(any("1 行日记读不出来" in w for w in snap["warnings"]), f"缺少坏行提示：{snap['warnings']}")
    return "坏行跳过并提示，好行正常"


def case_empty_journal():
    root = build_root("empty_journal")
    write_journal(root, [])
    write_profile(root)
    write_config(root)
    write_db(root)
    snap = run_snapshot(root)
    assert_(snap["journal"] == [], "空文件应返回空列表")
    assert_(snap["bot"]["state"], "空文件时状态仍要有文案")
    return "空文件不崩，状态正常"


def case_missing_db():
    root = build_root("missing_db")
    write_journal(root, ['{"time":"2026-10-27 22:56","content":"一条日记","auto":true}'])
    write_profile(root)
    write_config(root)
    snap = run_snapshot(root)
    assert_(snap["reading"] == {} or not snap["reading"].get("book"), "没有数据库时不应有读书进度")
    assert_(any("数据库文件找不到" in w for w in snap["warnings"]), f"缺少数据库提示：{snap['warnings']}")
    assert_(len(snap["journal"]) == 1, "日记不受数据库影响")
    return "数据库缺失时日记照常，提示明确"


def case_no_profile():
    root = build_root("no_profile")
    write_journal(root, ['{"time":"2026-10-27 22:56","content":"一条日记","auto":true}'])
    write_config(root)
    write_db(root)
    snap = run_snapshot(root)
    assert_(any("记忆档案" in w for w in snap["warnings"]), f"缺少档案提示：{snap['warnings']}")
    return "档案缺失时提示，不影响日记"


CASES = [
    ("E-00 正常数据", case_normal),
    ("E-01 日记文件缺失", case_missing_journal),
    ("E-02 坏行跳过", case_bad_line),
    ("E-03 空日记文件", case_empty_journal),
    ("E-04 数据库缺失", case_missing_db),
    ("E-05 档案缺失", case_no_profile),
]


def main() -> int:
    os.makedirs(TMP, exist_ok=True)
    print("== 边界用例（全部在临时副本上跑，不碰真实数据）==\n")
    for name, fn in CASES:
        case(name, fn)

    ok = True
    for name, passed, detail in RESULTS:
        ok = ok and passed
        print(f"{'  ' if passed else '!!'} {name.ljust(18)} {'OK' if passed else 'FAIL'}  {detail}")

    print()
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
