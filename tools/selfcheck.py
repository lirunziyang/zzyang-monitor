"""启动自检：不开窗口，确认服务、静态资源、接口三件事都正常。

用法：
    runtime\\python.exe tools\\selfcheck.py

退出码：0 = 全部通过；1 = 有失败项
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(BASE, "runtime", "python.exe")
APP = os.path.join(BASE, "app.py")

CHECKS = []


def check(name: str, fn):
    try:
        detail = fn()
        CHECKS.append((name, True, detail))
    except Exception as e:
        CHECKS.append((name, False, f"{type(e).__name__}: {e}"))


def wait_url(proc, timeout: float = 15.0) -> str:
    end = time.time() + timeout
    while time.time() < end:
        line = proc.stdout.readline()
        if line:
            text = line.strip()
            if text.startswith("http://"):
                return text
        if proc.poll() is not None:
            err = proc.stderr.read()
            raise RuntimeError("服务进程提前退出：" + str(err)[:500])
    raise RuntimeError("等待服务地址超时")


def fetch(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": "zz-selfcheck"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def main() -> int:
    if not os.path.exists(PY):
        print(f"[错误] 找不到运行环境：{PY}")
        return 1

    proc = subprocess.Popen(
        [PY, APP, "--serve"],
        cwd=BASE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    try:
        url = wait_url(proc)
        print(f"== 启动自检 == {url}\n")

        def index():
            code, body = fetch(url)
            assert code == 200, f"HTTP {code}"
            text = body.decode("utf-8", "replace")
            assert "子漾监测" in text, "首页缺少标题"
            return f"HTTP 200, {len(body)} 字节"

        def css():
            code, body = fetch(url + "style.css")
            assert code == 200, f"HTTP {code}"
            assert b"--accent" in body, "样式变量缺失"
            return f"HTTP 200, {len(body)} 字节"

        def js():
            code, body = fetch(url + "app.js")
            assert code == 200, f"HTTP {code}"
            text = body.decode("utf-8", "replace")
            assert "getSnapshot" in text, "脚本缺少入口函数"
            return f"HTTP 200, {len(body)} 字节"

        def api():
            code, body = fetch(url + "api/snapshot")
            assert code == 200, f"HTTP {code}"
            data = json.loads(body)
            assert data.get("ok") is True, "snapshot.ok 不为 true"
            assert isinstance(data.get("journal"), list), "journal 不是数组"
            assert data.get("bot", {}).get("state"), "缺少状态文案"
            return f"ok=true, 日记 {len(data['journal'])} 条, 状态「{data['bot']['state']}」"

        for name, fn in (("首页", index), ("样式", css), ("脚本", js), ("接口", api)):
            check(name, fn)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    ok = True
    for name, passed, detail in CHECKS:
        ok = ok and passed
        print(f"{'  ' if passed else '!!'} {name.ljust(6)} {'OK' if passed else 'FAIL'}  {detail}")

    print()
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
