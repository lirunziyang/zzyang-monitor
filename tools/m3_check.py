"""M3 功能验证：往年今天、常提到的词、记忆档案、标星批注与备份。

数据用临时副本；星标文件先备份再恢复，跑完不改变你原来的星标。

用法：
    runtime\\python.exe tools\\m3_check.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(BASE, "runtime", "python.exe")
APP = os.path.join(BASE, "app.py")
TMP = os.path.join(BASE, "tests", ".tmp_m3")
DATA = os.path.join(BASE, "data")
STARS = os.path.join(DATA, "stars.json")
BACKUP = os.path.join(DATA, "backup")

RESULTS = []


def case(name, fn):
    try:
        RESULTS.append((name, True, fn()))
    except Exception as e:
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))


def assert_(cond, msg):
    if not cond:
        raise AssertionError(msg)


def build_root(name: str) -> str:
    root = os.path.join(TMP, name)
    if os.path.exists(root):
        shutil.rmtree(root, ignore_errors=True)
    for sub in ("plugins/astrbot_plugin_edge_tts/data/books", "config"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    with open(os.path.join(root, "config/astrbot_plugin_edge_tts_config.json"), "w", encoding="utf-8") as f:
        json.dump({"autonomy_enable": True}, f)
    with open(os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/profile_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"count": 42, "ts": 1.0, "at": "2026-10-27 21:30"}, f)
    return root


def write_journal(root: str, entries: list[tuple[str, str, bool]]) -> None:
    path = os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/journal.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for ts, content, auto in entries:
            f.write(json.dumps({"time": ts, "content": content, "auto": auto}, ensure_ascii=False) + "\n")


def empty_db(root: str) -> None:
    con = sqlite3.connect(os.path.join(root, "data_v4.db"))
    con.execute(
        "CREATE TABLE preferences (created_at TEXT, updated_at TEXT, id INTEGER PRIMARY KEY, "
        "scope TEXT, scope_id TEXT, key TEXT, value TEXT)"
    )
    con.commit()
    con.close()


def run_check(root: str) -> dict:
    env = dict(os.environ)
    env["ZZYANG_DATA_ROOT"] = root
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([PY, APP, "--check"], cwd=BASE, capture_output=True, timeout=120, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:800])
    return json.loads(proc.stdout.decode("utf-8", "replace"))


def sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def g_history():
    root = build_root("history")
    today = time.strftime("%Y-%m-%d")
    last_year = str(int(today[:4]) - 1) + today[4:]
    write_journal(
        root,
        [
            (f"{today} 21:00", "今天写的这一篇。", True),
            (f"{last_year} 20:00", "去年同一天写的那一篇。", True),
            ("2025-01-01 10:00", "元旦写的，不算。", True),
        ],
    )
    empty_db(root)
    snap = run_check(root)
    hist = snap["history"]
    assert_(len(hist) == 1, f"应只有 1 条往年今天，实际 {len(hist)}")
    assert_(hist[0]["date"] == last_year, f"日期不对：{hist[0]['date']}")
    return f"命中 {last_year} 那条，元旦那条被排除"


def g_topics():
    root = build_root("topics")
    lines = []
    for i in range(8):
        lines.append((f"2026-10-{10+i} 20:00", f"第{i}天，我又翻开《长日将尽》，管家的话让我想了很久。", True))
    for i in range(6):
        lines.append((f"2026-09-{10+i} 20:00", "今天和浩宇聊到记忆，他说会记住重要的事。", False))
    write_journal(root, lines)
    empty_db(root)
    snap = run_check(root)
    words = [t["word"] for t in snap["topics"]]
    assert_(words, "没有统计出任何词")
    assert_(any("长日将尽" in w or "管家" in w for w in words), f"没抓到明显的高频词：{words}")
    counts = [t["count"] for t in snap["topics"]]
    assert_(counts == sorted(counts, reverse=True), "结果没有按次数排序")
    return f"共 {len(words)} 个词，含「{words[0]}」"


def g_memory():
    root = build_root("memory")
    write_journal(root, [("2026-10-27 20:00", "一条日记", True)])
    empty_db(root)
    md = """【使用说明】这是说明。
（自动整理于 2026-10-27 21:30）

【用户是谁】
- 用户叫李浩宇。
- 用户是大学生。

【关系和重要节点】
- 机器人名「润子漾」。
"""
    with open(os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/memory_profile.md"), "w", encoding="utf-8") as f:
        f.write(md)
    snap = run_check(root)
    mem = snap["memory"]
    assert_(mem["exists"], "应识别到档案存在")
    titles = [s["title"] for s in mem["sections"]]
    assert_("用户是谁" in titles and "关系和重要节点" in titles, f"分段不对：{titles}")
    assert_(mem["chars"] > 50, "字数统计不对")
    return f"{len(mem['sections'])} 段：{'、'.join(titles[:3])}"


def g_note_and_backup():
    root = build_root("note")
    write_journal(root, [("2026-10-27 20:00", "这条要用来测试批注。", True)])
    empty_db(root)

    # 备份用户真实星标
    had_stars = os.path.exists(STARS)
    tmp_stars = STARS + ".testbak"
    if had_stars:
        shutil.copy2(STARS, tmp_stars)
    had_backup = os.path.exists(BACKUP)
    tmp_backup = BACKUP + ".testbak"
    if had_backup:
        shutil.move(BACKUP, tmp_backup)

    env = dict(os.environ)
    env["ZZYANG_DATA_ROOT"] = root
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [PY, APP, "--serve"],
        cwd=BASE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    try:
        url = None
        end = time.time() + 15
        while time.time() < end and url is None:
            line = proc.stdout.readline()
            if line and line.strip().startswith("http://"):
                url = line.strip()
        assert_(url, "服务未启动")

        def get(path):
            with urllib.request.urlopen(url + path, timeout=10) as r:
                return json.loads(r.read())

        def post(path, payload, allow_error=False):
            req = urllib.request.Request(
                url + path,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if not allow_error:
                    raise
                return json.loads(e.read())

        snap = get("api/snapshot")
        entry = snap["journal"][0]

        # 未标星就写批注 → 应被拒绝
        bad = post("api/note", {"id": entry["id"], "note": "先写批注"}, allow_error=True)
        assert_(bad.get("ok") is False, "没标星时不该允许写批注")

        r1 = post("api/star", {"id": entry["id"], "time": entry["time"], "preview": "x"})
        assert_(r1["starred"] is True, "标星失败")
        assert_(os.path.exists(os.path.join(BACKUP)), "标星后应产生备份")

        r2 = post("api/note", {"id": entry["id"], "note": "这句是我写给自己的。"})
        assert_(r2.get("ok") is True, f"写批注失败：{r2}")
        note = r2["stars"][entry["id"]]["note"]
        assert_(note == "这句是我写给自己的。", f"批注内容不对：{note}")

        snap2 = get("api/snapshot")
        assert_(snap2["stars"][entry["id"]]["note"] == note, "重新读取后批注丢失")

        # 机器人文件不能被改
        journal_path = os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/journal.jsonl")
        before = sha(journal_path)
        post("api/star", {"id": entry["id"], "time": entry["time"], "preview": "x"})  # 取消
        assert_(sha(journal_path) == before, "日记文件被改动了")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        # 恢复用户真实星标
        if os.path.exists(STARS):
            os.remove(STARS)
        if had_stars:
            shutil.move(tmp_stars, STARS)
        if os.path.exists(BACKUP):
            shutil.rmtree(BACKUP, ignore_errors=True)
        if had_backup:
            shutil.move(tmp_backup, BACKUP)

    return "未标星拒绝、标星后可写、重新读取仍在、日记未被改、备份已生成"


CASES = [
    ("G-01 往年今天", g_history),
    ("G-02 常提到的词", g_topics),
    ("G-03 记忆档案", g_memory),
    ("G-04 批注与备份", g_note_and_backup),
]


def main() -> int:
    os.makedirs(TMP, exist_ok=True)
    print("== M3 功能验证（临时副本）==\n")
    for name, fn in CASES:
        case(name, fn)

    ok = True
    for name, passed, detail in RESULTS:
        ok = ok and passed
        print(f"{'  ' if passed else '!!'} {name.ljust(16)} {'OK' if passed else 'FAIL'}  {detail}")
    print()
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
