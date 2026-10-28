"""界面自检的入口：实际逻辑在 tools\\ui_check.ps1 里。

为什么要绕到 PowerShell：浏览器必须由桌面会话直接拉起，
从受限的 Python 子进程里启动会卡在加载页面前（实测）。
所以这里只负责转调那个脚本。

用法：
    runtime\\python.exe tools\\ui_check.py
    （或者直接双击 tools\\界面自检.bat）
"""
from __future__ import annotations

import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS1 = os.path.join(BASE, "tools", "ui_check.ps1")


def main() -> int:
    if not os.path.exists(PS1):
        print(f"!! 找不到 {PS1}")
        return 1
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS1],
        cwd=BASE,
    )
    if proc.returncode != 0:
        print()
        print("提示：如果上面提示拿不到结果，请改用普通桌面窗口运行：")
        print("      tools\\界面自检.bat")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
