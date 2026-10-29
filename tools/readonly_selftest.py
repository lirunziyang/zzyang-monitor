"""只读性检查自身的测试：确认它真的能发现改动，而不是永远返回 PASS。

用法：python tools\\readonly_selftest.py
"""

import importlib.util
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(BASE, "tools", "readonly_check.py")

spec = importlib.util.spec_from_file_location("readonly_check", MOD)
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((name, True, detail or ""))
    except AssertionError as e:
        results.append((name, False, str(e)))
    except Exception as e:  # noqa: BLE001
        results.append((name, False, f"{type(e).__name__}: {e}"))


def t_strict_same():
    b = {"x.jsonl": {"exists": True, "kind": "strict", "sha": "aaa", "size": 10}}
    a = {"x.jsonl": {"exists": True, "kind": "strict", "sha": "aaa", "size": 10}}
    rows = rc.compare(b, a)
    assert rows[0][1] == "SAME" and rows[0][3] is True, f"同内容应判 SAME，实际 {rows[0]}"
    return "同内容 → SAME"


def t_strict_changed():
    b = {"x.jsonl": {"exists": True, "kind": "strict", "sha": "aaa", "size": 10}}
    a = {"x.jsonl": {"exists": True, "kind": "strict", "sha": "bbb", "size": 10}}
    rows = rc.compare(b, a)
    assert rows[0][1] == "CHANGED" and rows[0][3] is False, f"内容变了应判 CHANGED，实际 {rows[0]}"
    return "内容变化 → CHANGED"


def t_meta_busy():
    b = {"db": {"exists": True, "kind": "meta", "sha": "", "size": 10, "mtime": 1}}
    a = {"db": {"exists": True, "kind": "meta", "sha": "", "size": 12, "mtime": 2}}
    rows = rc.compare(b, a)
    assert rows[0][1] == "BUSY" and rows[0][3] is True, f"元信息变化应判 BUSY，实际 {rows[0]}"
    return "元信息变化 → BUSY（允许机器人自己写）"


def t_disappear():
    b = {"gone.json": {"exists": True, "kind": "strict", "sha": "a", "size": 1}}
    a = {"gone.json": {"exists": False}}
    rows = rc.compare(b, a)
    assert rows[0][1] == "CHANGED" and rows[0][3] is False, f"文件消失应判失败，实际 {rows[0]}"
    return "文件消失 → CHANGED"

def t_coverage():
    names = [os.path.basename(p) for p in rc.STRICT + rc.META]
    need = ["journal.jsonl", "profile_meta.json", "short_memory.json"]
    miss = [n for n in need if n not in names]
    # 新文件只有在存在时才纳入，所以这里只要求“存在的都纳入了”
    for n in need:
        full = None
        for p in rc.STRICT + rc.META:
            if os.path.basename(p) == n:
                full = p
                break
        if full is not None and not os.path.exists(full):
            miss.remove(n)
    assert not miss, f"这些存在的文件没被纳入校验：{miss}"
    return f"覆盖 {len(rc.STRICT)} 个严格比对 + {len(rc.META)} 个元信息"


def t_structure_short_absent():
    snap = {"journal": [], "memory": {"sections": [], "chars": 0}}
    rows = rc.structure_checks(snap)
    names = [r[0] for r in rows]
    assert "短期记忆" in names, f"结构检查里没有短期记忆：{names}"
    assert "记忆健康" in names, f"结构检查里没有记忆健康：{names}"
    return "短期记忆/记忆健康 都在检查项里"


check("严格比对：同内容", t_strict_same)
check("严格比对：内容变化", t_strict_changed)
check("元信息：变化可容忍", t_meta_busy)
check("严格比对：文件消失", t_disappear)
check("覆盖范围", t_coverage)
check("结构检查项", t_structure_short_absent)

print("== 只读性检查自测 ==\n")
bad = 0
for name, ok, detail in results:
    mark = "OK  " if ok else "FAIL"
    if not ok:
        bad += 1
    print(f"   {name:<20} {mark}  {detail}")

print()
if bad:
    print(f"RESULT: FAIL  ({bad} 项失败)")
    sys.exit(1)
print(f"RESULT: PASS  ({len(results)} 项)")
