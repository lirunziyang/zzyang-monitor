"""M4 验证：备份轮转、结构断言能报警、文档与实际一致。

用法：
    runtime\\python.exe tools\\m4_check.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import store  # noqa: E402
import readonly_check  # noqa: E402

TMP = os.path.join(BASE, "tests", ".tmp_m4")
RESULTS = []


def case(name, fn):
    try:
        RESULTS.append((name, True, fn()))
    except Exception as e:
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))


def assert_(cond, msg):
    if not cond:
        raise AssertionError(msg)


def h_backup_rotation():
    """制造 8 次标星，备份目录最多留 5 份，且内容是合法的星标文件。"""
    stars_backup = store.STARS + ".testbak"
    backup_dir = store.BACKUP_DIR
    backup_bak = backup_dir + ".testbak"
    had_stars = os.path.exists(store.STARS)
    had_backup = os.path.exists(backup_dir)

    if had_stars:
        shutil.copy2(store.STARS, stars_backup)
    if had_backup:
        shutil.move(backup_dir, backup_bak)

    try:
        for i in range(8):
            store.toggle(f"entry-{i}", f"2026-10-27 2{i // 6}:00", f"测试条目 {i}")
            time.sleep(0.02)
        files = sorted(f for f in os.listdir(backup_dir) if f.startswith("stars-"))
        assert_(len(files) <= store.KEEP_BACKUPS, f"备份应最多 {store.KEEP_BACKUPS} 份，实际 {len(files)}")
        assert_(len(files) >= 1, "没有生成任何备份")
        with open(os.path.join(backup_dir, files[-1]), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert_("items" in data, "备份内容不是星标文件")
        assert_(data.get("version") == 2, "备份里的版本号不对")
        return f"{len(files)} 份备份，最新一份 {len(data['items'])} 条"
    finally:
        if os.path.exists(store.STARS):
            os.remove(store.STARS)
        if had_stars:
            shutil.move(stars_backup, store.STARS)
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)
        if had_backup:
            shutil.move(backup_bak, backup_dir)


def h_structure_warns():
    """把快照弄坏，结构断言必须报错；伪造正文必须被逐字校验抓到。"""
    from core import data as botdata

    real = botdata.read_journal()
    assert_(real, "真实日记为空，无法构造用例")
    good = {
        "journal": [real[0]],
        "reading": {"book": "a.txt", "pos": 1, "total": 10, "percent": 10.0, "updated_at": "2026-10-27"},
        "books": [{"book": "a.txt", "pos": 1}],
        "memory": {"exists": True, "sections": [], "chars": 0},
        "settings": {"refresh_seconds": 30, "page_size": 60, "timeline_limit": 40},
        "bot": {"state": "安静待着"},
    }
    ok_rows = readonly_check.structure_checks(good)
    bad_ok = [r for r in ok_rows if not r[1]]
    assert_(not bad_ok, f"正常快照不该报错：{bad_ok}")

    # 伪造一条正文：必须被「日记原文一致」抓到
    forged = json.loads(json.dumps(good, ensure_ascii=False))
    forged["journal"][0]["content"] = "这是程序自己编的一句话，原文里没有。"
    rows = readonly_check.structure_checks(forged)
    assert_(
        any(r[0] == "日记原文一致" and not r[1] for r in rows),
        "伪造的正文没有被逐字校验抓到",
    )

    broken = json.loads(json.dumps(good, ensure_ascii=False))
    broken["journal"][0]["kind"] = "weird"
    broken["settings"].pop("page_size")
    del broken["memory"]["sections"]
    bad_rows = readonly_check.structure_checks(broken)
    failed = [r[0] for r in bad_rows if not r[1]]
    assert_("日记字段" in failed, f"未知类型没有被发现：{failed}")
    assert_("设置项" in failed, f"缺设置项没有被发现：{failed}")
    assert_("记忆档案" in failed, f"档案缺字段没有被发现：{failed}")

    empty = {"journal": [], "bot": {"state": ""}}
    rows = readonly_check.structure_checks(empty)
    assert_(any(r[0] == "状态文案" and not r[1] for r in rows), "空状态文案没有被发现")
    return "正常通过；伪造正文/类型异常/缺字段/空状态都能报出来"


def h_docs():
    """README / PRD / PLAN 里的关键承诺都在。"""
    readme = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
    prd = open(os.path.join(BASE, "PRD.md"), encoding="utf-8").read()
    plan = open(os.path.join(BASE, "PLAN.md"), encoding="utf-8").read()

    for tool in ("selfcheck.py", "readonly_check.py", "edge_check.py", "feature_check.py", "m3_check.py", "m4_check.py"):
        assert_(tool in readme, f"README 没有提到 {tool}")

    for claim in ("只读", "journal.jsonl", "stars.json"):
        assert_(claim in prd, f"PRD 缺少关键内容：{claim}")

    for m in ("M0", "M1", "M2", "M3", "M4"):
        assert_(m in plan, f"PLAN 缺少里程碑 {m}")

    assert_("子漾监测.vbs" in readme, "README 没写怎么启动")
    return "README/PRD/PLAN 关键内容齐全"


CASES = [
    ("H-01 备份轮转", h_backup_rotation),
    ("H-02 结构断言", h_structure_warns),
    ("H-03 文档一致", h_docs),
]


def main() -> int:
    os.makedirs(TMP, exist_ok=True)
    print("== M4 验证 ==\n")
    for name, fn in CASES:
        case(name, fn)

    ok = True
    for name, passed, detail in RESULTS:
        ok = ok and passed
        print(f"{'  ' if passed else '!!'} {name.ljust(14)} {'OK' if passed else 'FAIL'}  {detail}")
    print()
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
