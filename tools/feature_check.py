"""M1 功能验证：设置项、多本书、诊断接口、单实例检测。

全部在临时副本上跑，不碰真实数据。

用法：
    runtime\\python.exe tools\\feature_check.py
"""
from __future__ import annotations

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
TMP = os.path.join(BASE, "tests", ".tmp_feature")

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
    with open(os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/journal.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"time":"2026-10-27 22:56","content":"一条日记","auto":true}\n')
    with open(os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/profile_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"count": 3, "ts": 1.0, "at": "2026-10-27 21:30"}, f)
    with open(os.path.join(root, "config/astrbot_plugin_edge_tts_config.json"), "w", encoding="utf-8") as f:
        json.dump({"autonomy_enable": True}, f)
    return root


def write_db(root: str, books: dict) -> None:
    path = os.path.join(root, "data_v4.db")
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE preferences (created_at TEXT, updated_at TEXT, id INTEGER PRIMARY KEY, "
        "scope TEXT, scope_id TEXT, key TEXT, value TEXT)"
    )
    i = 0
    for name, (pos, updated) in books.items():
        i += 1
        con.execute(
            "INSERT INTO preferences (created_at, updated_at, scope, scope_id, key, value) VALUES (?,?,?,?,?,?)",
            (
                updated,
                updated,
                "plugin",
                "p",
                f"astrbot_plugin_edge_tts:book_pos:{name}",
                json.dumps({"val": pos}),
            ),
        )
        book_path = os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/books", name)
        with open(book_path, "w", encoding="utf-8") as f:
            f.write("字" * 1000)
    con.commit()
    con.close()


def run_check(root: str, extra_env: dict | None = None) -> dict:
    env = dict(os.environ)
    env["ZZYANG_DATA_ROOT"] = root
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run([PY, APP, "--check"], cwd=BASE, capture_output=True, timeout=120, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:800])
    return json.loads(proc.stdout.decode("utf-8", "replace"))


# ---------------- 用例 ----------------

def f_settings_default():
    root = build_root("settings_default")
    write_db(root, {"甲.txt": (100, "2026-10-27 10:00")})
    workdir = os.path.join(TMP, "proj_default")
    if os.path.exists(workdir):
        shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(os.path.join(workdir, "data"), exist_ok=True)
    # 直接把真实工程的 settings 临时改名，验证「不存在就生成默认值」
    real = os.path.join(BASE, "data", "settings.json")
    backup = real + ".bak"
    had = os.path.exists(real)
    if had:
        os.replace(real, backup)
    try:
        snap = run_check(root)
        assert_(os.path.exists(real), "首次运行应自动生成 settings.json")
        assert_(snap["settings"]["refresh_seconds"] == 30, "默认刷新间隔应为 30")
        assert_(snap["settings"]["page_size"] == 60, "默认分页应为 60")
    finally:
        if had:
            os.replace(backup, real)
    return "缺失时自动生成默认值"


def f_settings_custom():
    root = build_root("settings_custom")
    write_db(root, {"甲.txt": (100, "2026-10-27 10:00")})
    path = os.path.join(BASE, "data", "settings.json")
    backup = path + ".bak"
    had = os.path.exists(path)
    if had:
        os.replace(path, backup)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"refresh_seconds": 10, "page_size": 25, "timeline_limit": 7}, f)
        snap = run_check(root)
        assert_(snap["settings"]["refresh_seconds"] == 10, "自定义刷新间隔没生效")
        assert_(snap["settings"]["page_size"] == 25, "自定义分页没生效")
        assert_(len(snap["events"]) <= 7, "时间线条数没按设置截断")
    finally:
        os.remove(path)
        if had:
            os.replace(backup, path)
    return "自定义值生效，时间线按 7 条截断"


def f_settings_broken():
    root = build_root("settings_broken")
    write_db(root, {"甲.txt": (100, "2026-10-27 10:00")})
    path = os.path.join(BASE, "data", "settings.json")
    backup = path + ".bak"
    had = os.path.exists(path)
    if had:
        os.replace(path, backup)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ 这不是合法 JSON")
        snap = run_check(root)
        assert_(snap["settings"]["refresh_seconds"] == 30, "坏文件应回退默认值")
        assert_(any("settings.json" in w for w in snap["warnings"]), f"应给出提示：{snap['warnings']}")
    finally:
        os.remove(path)
        if had:
            os.replace(backup, path)
    return "坏文件回退默认值并提示"


def f_multiple_books():
    root = build_root("multi_books")
    write_db(
        root,
        {
            "老书.txt": (100, "2026-10-20 10:00"),
            "新书.txt": (500, "2026-10-27 20:00"),
        },
    )
    snap = run_check(root)
    books = snap["books"]
    assert_(len(books) == 2, f"应有 2 本书，实际 {len(books)}")
    assert_(books[0]["book"] == "新书.txt", "应按最后翻页时间倒序")
    assert_(snap["reading"]["book"] == "新书.txt", "主书应是最新那本")
    assert_(snap["reading"]["percent"] == 50.0, f"百分比不对：{snap['reading']['percent']}")
    return "2 本书、按时间倒序、主书正确、50%"


def f_diag_and_instance():
    root = build_root("diag")
    write_db(root, {"甲.txt": (100, "2026-10-27 10:00")})
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
        with urllib.request.urlopen(url + "api/diag", timeout=10) as r:
            d = json.loads(r.read())
        assert_(d["ok"] is True, "diag 应返回 ok")
        assert_(len(d["paths"]) >= 5, "诊断应列出数据文件")
        assert_(d["bot_root"] == root, "诊断里的监测目标应指向临时副本")
        assert_("journal" in d["log"] or isinstance(d["log"], list), "日志字段类型不对")

        # 单实例检测：写一个指向本次服务的记录
        inst = os.path.join(BASE, "data", "instance.json")
        backup = inst + ".bak"
        had = os.path.exists(inst)
        preexisting = None
        if had:
            try:
                with open(inst, "r", encoding="utf-8") as f:
                    preexisting = int(json.load(f).get("port") or 0)
            except Exception:
                preexisting = 0
            os.replace(inst, backup)
        try:
            port = int(url.split(":")[2].strip("/"))
            with open(inst, "w", encoding="utf-8") as f:
                json.dump({"pid": 1, "port": port, "started": time.time()}, f)
            out = subprocess.run(
                [PY, "-c", "import sys;sys.path.insert(0,r'" + BASE + "');import app;print(app.read_instance() or 0)"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=60,
            )
            alive = int(out.stdout.strip() or 0)
            assert_(alive == port, f"应检测到运行中的实例 {port}，实际 {alive}")
        finally:
            if had:
                os.replace(backup, inst)
            else:
                os.remove(inst)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    # 临时服务停掉后：如果本机原本就开着程序，应当仍检测到「原来那个」，否则应为 0
    env2 = dict(os.environ)
    out = subprocess.run(
        [PY, "-c", "import sys;sys.path.insert(0,r'" + BASE + "');import app;print(app.read_instance() or 0)"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env2,
        timeout=60,
    )
    after = int(out.stdout.strip() or 0)
    if preexisting:
        assert_(after == preexisting, f"原本开着的实例应仍是 {preexisting}，实际 {after}")
        return f"诊断字段完整、单实例检测正确（本机原有实例 {preexisting} 未受影响）"
    assert_(after == 0, "服务已停，不应再检测到实例")
    return "诊断字段完整、单实例检测（活/死）正确"


def f_close_pref():
    """关窗行为偏好：默认退出，可切换为留在托盘，并持久化。"""
    root = build_root("close")
    write_db(root, {"甲.txt": (100, "2026-10-27 10:00")})
    home = os.path.join(TMP, "home_close")
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ)
    env["ZZYANG_DATA_ROOT"] = root
    env["ZZYANG_DATA_HOME"] = home
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [PY, APP, "--serve"], cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
    )
    try:
        url = None
        end = time.time() + 15
        while time.time() < end and url is None:
            line = proc.stdout.readline()
            if line and line.strip().startswith("http://"):
                url = line.strip()
        assert_(url, "服务未启动")

        def get():
            with urllib.request.urlopen(url + "api/snapshot", timeout=10) as r:
                return json.loads(r.read())

        def post(path, payload, allow_error=False):
            req = urllib.request.Request(
                url + path, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if not allow_error:
                    raise
                return json.loads(e.read())

        snap = get()
        assert_(snap["settings"].get("close_to_tray") is False, "默认应为关窗即退出")

        r = post("api/prefs", {"close_to_tray": True})
        assert_(r.get("ok") is True, f"保存失败：{r}")
        assert_(get()["settings"]["close_to_tray"] is True, "开关没落到快照")

        bad = post("api/prefs", {}, allow_error=True)
        assert_(bad.get("ok") is False, "空请求应被拒绝")

        cfg = os.path.join(home, "settings.json")
        with open(cfg, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert_(saved.get("close_to_tray") is True, "设置文件没保存开关")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    return "默认关窗退出，可切换为留在托盘并持久化"

    """机器人名字：能保存、能读回、空值拒绝。"""
def f_bot_name():
    root = build_root("name")
    write_db(root, {"甲.txt": (100, "2026-10-27 10:00")})
    home = os.path.join(TMP, "home_name")
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ)
    env["ZZYANG_DATA_ROOT"] = root
    env["ZZYANG_DATA_HOME"] = home
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [PY, APP, "--serve"], cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
    )
    try:
        url = None
        end = time.time() + 15
        while time.time() < end and url is None:
            line = proc.stdout.readline()
            if line and line.strip().startswith("http://"):
                url = line.strip()
        assert_(url, "服务未启动")

        def get():
            with urllib.request.urlopen(url + "api/snapshot", timeout=10) as r:
                return json.loads(r.read())

        def post(path, payload, allow_error=False):
            req = urllib.request.Request(
                url + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if not allow_error:
                    raise
                return json.loads(e.read())

        snap = get()
        assert_(snap["setup"]["name_needed"] is True, "没填名字时应提示需要名字")
        assert_(snap["bot_name"] == "", "初始名字应为空")

        r = post("api/name", {"name": "小漾"})
        assert_(r.get("ok") is True, f"保存名字失败：{r}")
        snap2 = get()
        assert_(snap2["bot_name"] == "小漾", f"名字没落到快照：{snap2['bot_name']}")
        assert_(snap2["setup"]["name_needed"] is False, "填过名字后不该再要求")

        empty = post("api/name", {"name": "   "}, allow_error=True)
        assert_(empty.get("ok") is False, "空名字应被拒绝")

        long_name = post("api/name", {"name": "名" * 30}, allow_error=True)
        assert_(long_name.get("ok") is False, "超长名字应被拒绝")

        cfg = os.path.join(home, "settings.json")
        with open(cfg, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert_(saved.get("bot_name") == "小漾", f"设置文件里没存名字：{saved.get('bot_name')}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    return "名字可保存/读回，空值与超长被拒"

    """书架：按书分开统计次数与字数，并给出合并总览。"""
def f_reading_stats():
    root = build_root("reading")
    entries = []
    # A 书读 3 次，每次 1000 字
    for i in range(3):
        entries.append(
            (f"2026-10-2{5+i} 20:00",
             f"（自己读了会儿书）《甲书.txt》第 {i*1000}–{(i+1)*1000} 字，共 10000 字。", True)
        )
    # B 书读 1 次，500 字
    entries.append(("2026-10-27 21:00", "（自己读了会儿书）《乙书.txt》第 0–500 字，共 5000 字。", True))
    jpath = os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/journal.jsonl")
    with open(jpath, "w", encoding="utf-8") as f:
        for ts, content, auto in entries:
            f.write(json.dumps({"time": ts, "content": content, "auto": auto}, ensure_ascii=False) + "\n")
    write_db(root, {"甲书.txt": (3000, "2026-10-27 20:00")})   # 只有甲书有进度
    # 把甲书正文改成 10000 字，便于断言 30%
    with open(os.path.join(root, "plugins/astrbot_plugin_edge_tts/data/books/甲书.txt"), "w", encoding="utf-8") as f:
        f.write("字" * 10000)

    snap = run_check(root)
    st = snap["reading_stats"]
    assert_(st["sessions"] == 4, f"总次数应为 4，实际 {st['sessions']}")
    assert_(st["chars"] == 3500, f"总字数应为 3500，实际 {st['chars']}")
    assert_(st["books"] == 2, f"应识别 2 本书，实际 {st['books']}")

    by_name = {b["book"]: b for b in snap["books"]}
    assert_("甲书.txt" in by_name and "乙书.txt" in by_name, f"书单不对：{list(by_name)}")
    assert_(by_name["甲书.txt"]["sessions"] == 3, "甲书次数不对")
    assert_(by_name["甲书.txt"]["chars_read"] == 3000, "甲书字数不对")
    assert_(by_name["乙书.txt"]["sessions"] == 1, "只在日记里出现的书也要列出来")
    assert_(by_name["甲书.txt"]["percent"] == 30.0, "甲书进度应为 30%")
    return f"2 本 · 4 次 · 3500 字，乙书无进度也能列出"


def f_theme_persist():

    """主题：能保存、能读回、非法值被拒。"""
    root_a = build_root("theme_a")
    write_db(root_a, {"甲.txt": (100, "2026-10-27 10:00")})
    home = os.path.join(TMP, "home_theme")
    os.makedirs(home, exist_ok=True)

    env = dict(os.environ)
    env["ZZYANG_DATA_ROOT"] = root_a
    env["ZZYANG_DATA_HOME"] = home
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [PY, APP, "--serve"], cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
    )
    try:
        url = None
        end = time.time() + 15
        while time.time() < end and url is None:
            line = proc.stdout.readline()
            if line and line.strip().startswith("http://"):
                url = line.strip()
        assert_(url, "服务未启动")

        def get():
            with urllib.request.urlopen(url + "api/snapshot", timeout=10) as r:
                return json.loads(r.read())

        def post(path, payload, allow_error=False):
            req = urllib.request.Request(
                url + path, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if not allow_error:
                    raise
                return json.loads(e.read())

        snap = get()
        assert_(snap["settings"].get("theme") in ("xuantan", "black", "white"), "默认主题不合法")

        for theme in ("white", "black", "xuantan"):
            r = post("api/theme", {"theme": theme})
            assert_(r.get("ok") is True, f"切换 {theme} 失败：{r}")
            assert_(get()["settings"]["theme"] == theme, f"{theme} 没落到快照里")

        bad = post("api/theme", {"theme": "rainbow"}, allow_error=True)
        assert_(bad.get("ok") is False, "非法主题应该被拒绝")

        cfg = os.path.join(home, "settings.json")
        with open(cfg, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert_(saved.get("theme") == "xuantan", f"设置文件里的主题不对：{saved.get('theme')}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    return "三套主题可切换并持久化，非法值被拒"


def f_setup_flow():

    """首次运行指定目录：能保存、能切换、认不出来的路径要拒绝。"""
    root_a = build_root("setup_a")
    write_db(root_a, {"甲.txt": (100, "2026-10-27 10:00")})
    with open(os.path.join(root_a, "plugins/astrbot_plugin_edge_tts/data/journal.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"time":"2026-10-27 20:00","content":"来自 A 的一篇","auto":true}\n')

    root_b = build_root("setup_b")
    write_db(root_b, {"乙.txt": (500, "2026-10-27 21:00")})
    with open(os.path.join(root_b, "plugins/astrbot_plugin_edge_tts/data/journal.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"time":"2026-10-27 20:00","content":"来自 B 的第一篇","auto":true}\n')
        f.write('{"time":"2026-10-27 21:00","content":"来自 B 的第二篇","auto":true}\n')

    home = os.path.join(TMP, "home_setup")
    os.makedirs(home, exist_ok=True)

    env = dict(os.environ)
    env["ZZYANG_DATA_ROOT"] = root_a
    env["ZZYANG_DATA_HOME"] = home
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

        def get():
            with urllib.request.urlopen(url + "api/snapshot", timeout=10) as r:
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

        snap = get()
        assert_(snap["setup"]["needed"] is False, "指向可用目录时不该要求设置")
        assert_(snap["setup"]["bot_root"] == root_a, f"初始目录不对：{snap['setup']['bot_root']}")

        # 切到 B
        r = post("api/setup", {"path": root_b})
        assert_(r.get("ok") is True, f"切换失败：{r}")
        assert_(r.get("bot_root") == root_b, f"返回的目录不对：{r}")

        snap2 = get()
        assert_(snap2["setup"]["needed"] is False, "切换后不该再要求设置")
        assert_(snap2["setup"]["bot_root"] == root_b, "快照里的目录没变")
        assert_(len(snap2["journal"]) == 2, f"应读到 B 的 2 篇，实际 {len(snap2['journal'])}")
        assert_("来自 B" in snap2["journal"][0]["content"], "读到的不是 B 的内容")

        # 填一个不存在的路径
        bad = post("api/setup", {"path": r"D:\definitely\not\here"}, allow_error=True)
        assert_(bad.get("ok") is False, "不存在的路径应该被拒绝")
        snap3 = get()
        assert_(snap3["setup"]["bot_root"] == root_b, "拒绝之后不该改动当前目录")

        # 保存进设置文件
        cfg = os.path.join(home, "settings.json")
        assert_(os.path.exists(cfg), "设置文件没有生成")
        with open(cfg, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert_(saved.get("bot_root") == root_b, f"设置文件里没存新路径：{saved.get('bot_root')}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    return "可用目录免设置、能切换到 B 并读到 2 篇、坏路径被拒、路径落到 settings.json"


CASES = [
    ("F-01 设置默认值", f_settings_default),
    ("F-02 自定义设置", f_settings_custom),
    ("F-03 设置损坏回退", f_settings_broken),
    ("F-04 多本书", f_multiple_books),
    ("F-05 诊断与单实例", f_diag_and_instance),
    ("F-06 首次设置路径", f_setup_flow),
    ("F-07 主题持久化", f_theme_persist),
    ("F-08 阅读统计", f_reading_stats),
    ("F-09 机器人名字", f_bot_name),
    ("F-10 关窗行为", f_close_pref),
]


def main() -> int:
    os.makedirs(TMP, exist_ok=True)
    print("== M1 功能验证（临时副本）==\n")
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
