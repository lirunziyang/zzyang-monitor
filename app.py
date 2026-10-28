"""大肥鱼监测 —— 只读的本地监测窗口。

启动：双击「大肥鱼监测.vbs」
原理：本机起一个只监听 127.0.0.1 的只读服务，再用系统自带的 Edge
      以「应用窗口」模式打开它。不联网、不装额外运行库。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from core import data as botdata  # noqa: E402
from core import settings as zzsettings  # noqa: E402
from core import store  # noqa: E402

UI_DIR = os.path.join(BASE, "ui")
PROFILE_DIR = os.path.join(BASE, "data", "webprofile")
INSTANCE_FILE = os.path.join(BASE, "data", "instance.json")
STARTED_AT = time.time()
try:
    with open(os.path.join(BASE, "VERSION"), "r", encoding="utf-8-sig") as _vf:
        VERSION = _vf.read().strip() or "0.0.0"
except OSError:
    VERSION = "0.0.0"

EDGE_CANDIDATES = [
    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
]


def find_browser() -> str | None:
    for p in EDGE_CANDIDATES:
        if p and os.path.exists(p):
            return p
    # 注册表兜底
    try:
        import winreg

        for root, sub in (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        ):
            try:
                with winreg.OpenKey(root, sub) as k:
                    path, _ = winreg.QueryValueEx(k, None)
                    if path and os.path.exists(path):
                        return path
            except OSError:
                continue
    except Exception:
        pass
    return None


class Handler(SimpleHTTPRequestHandler):
    first_hit_at = 0.0
    hits = 0

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=UI_DIR, **kw)

    def log_message(self, fmt, *args):  # 安静运行
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not Handler.first_hit_at:
            Handler.first_hit_at = time.time()
        Handler.hits += 1
        if self.path.startswith("/api/diag"):
            return self._json(diag_payload())
        if self.path.startswith("/api/snapshot"):
            try:
                snap = botdata.build_snapshot()
                snap["stars"] = store.all_stars()
                snap["ok"] = True
                return self._json(snap)
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        if self.path.startswith("/api/health"):
            return self._json({"ok": True})
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/prefs"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                conf = zzsettings.load()
                conf.pop("_note", None)
                changed = {}
                for key in ("close_to_tray", "transparent"):
                    if isinstance(payload.get(key), bool):
                        conf[key] = payload[key]
                        changed[key] = payload[key]
                if not changed:
                    return self._json({"ok": False, "error": "没有可保存的项"}, 400)
                zzsettings.save(conf)
                zzsettings.reload()
                log(f"偏好已保存：{changed}")
                return self._json({"ok": True, "prefs": changed})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        if self.path.startswith("/api/name"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                name = str(payload.get("name", "")).strip()
                if not name:
                    return self._json({"ok": False, "error": "名字不能为空"}, 400)
                if len(name) > 20:
                    return self._json({"ok": False, "error": "名字最长 20 个字"}, 400)
                conf = zzsettings.load()
                conf.pop("_note", None)
                conf["bot_name"] = name
                zzsettings.save(conf)
                zzsettings.reload()
                log(f"机器人名字已设置：{name}")
                return self._json({"ok": True, "bot_name": name})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        if self.path.startswith("/api/theme"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                theme = str(payload.get("theme", "")).strip()
                if theme not in zzsettings.THEMES:
                    return self._json({"ok": False, "error": "未知主题"}, 400)
                conf = zzsettings.load()
                conf.pop("_note", None)
                conf["theme"] = theme
                if isinstance(payload.get("transparent"), bool):
                    conf["transparent"] = payload["transparent"]
                zzsettings.save(conf)
                zzsettings.reload()
                log(f"主题已切换：{theme}")
                return self._json({"ok": True, "theme": theme})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        if self.path.startswith("/api/setup"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                raw = str(payload.get("path", ""))
                root = botdata.resolve_root_input(raw)
                if not root:
                    return self._json(
                        {
                            "ok": False,
                            "error": "这个路径里没找到 AstrBot 的数据（需要包含 data_v4.db 或 plugins 文件夹）。"
                            "一般选到 AstrBot 目录下的 instance\\data。",
                        },
                        400,
                    )
                conf = zzsettings.load()
                conf.pop("_note", None)
                conf["bot_root"] = root
                zzsettings.save(conf)
                zzsettings.reload()
                botdata.configure_root(root)
                log(f"已设置监测目录：{botdata.BOT_ROOT}")
                return self._json({"ok": True, "bot_root": botdata.BOT_ROOT})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        if self.path.startswith("/api/uitest"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                path = os.path.join(BASE, "data", "uitest.json")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(
                        {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": payload.get("results", [])},
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        if self.path.startswith("/api/note"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                result = store.set_note(str(payload.get("id", "")), str(payload.get("note", "")))
                if not result.get("ok"):
                    return self._json({"ok": False, "error": result.get("error", "保存失败")}, 400)
                return self._json({"ok": True, "stars": result.get("items", {})})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        if not self.path.startswith("/api/star"):
            return self._json({"ok": False, "error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            starred = store.toggle(
                str(payload.get("id", "")),
                str(payload.get("time", "")),
                str(payload.get("preview", "")),
            )
            return self._json({"ok": True, "starred": starred, "stars": store.all_stars()})
        except Exception as e:
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def log(msg: str) -> None:
    """启动记录，出问题时能查到原因。只写在本程序自己的 data 目录。"""
    try:
        path = os.path.join(BASE, "data", "app.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 512 * 1024:
            os.remove(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def diag_payload() -> dict:
    """诊断信息：出问题时不用翻代码。"""
    items = [
        ("日记文件", botdata.JOURNAL),
        ("记忆档案", botdata.PROFILE_META),
        ("插件配置", botdata.PLUGIN_CFG),
        ("数据库", botdata.DB),
        ("书架目录", botdata.BOOKS_DIR),
        ("星标文件", store.STARS),
        ("设置文件", zzsettings.PATH),
    ]
    paths = []
    for label, p in items:
        row = {"label": label, "path": p, "exists": os.path.exists(p)}
        try:
            st = os.stat(p)
            row["size"] = st.st_size
            row["mtime"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
        except OSError:
            row["size"] = None
            row["mtime"] = ""
        paths.append(row)

    log_path = os.path.join(BASE, "data", "app.log")
    log_tail = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                log_tail = f.read().splitlines()[-20:]
        except OSError:
            pass

    return {
        "ok": True,
        "version": VERSION,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(STARTED_AT)),
        "uptime_sec": round(time.time() - STARTED_AT, 1),
        "hits": Handler.hits,
        "python": sys.version.split()[0],
        "base": BASE,
        "bot_root": botdata.BOT_ROOT,
        "root_source": botdata.ROOT_SOURCE,
        "root_usable": botdata.is_root_usable(),
        "paths": paths,
        "settings": zzsettings.load(),
        "log": log_tail,
    }


def read_instance() -> int | None:
    """已经在跑的话，返回它的端口。"""
    try:
        with open(INSTANCE_FILE, "r", encoding="utf-8") as f:
            info = json.load(f)
        port = int(info.get("port") or 0)
    except Exception:
        return None
    if not port:
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.8) as r:
            if r.status == 200:
                return port
    except Exception:
        return None
    return None


def write_instance(port: int) -> None:
    try:
        os.makedirs(os.path.dirname(INSTANCE_FILE), exist_ok=True)
        with open(INSTANCE_FILE, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "port": port, "started": time.time()}, f)
    except Exception:
        pass


def clear_instance() -> None:
    try:
        os.remove(INSTANCE_FILE)
    except OSError:
        pass


def _wait_launched(proc, timeout: float = 20.0) -> bool:
    """页面被真正请求到了才算窗口打开成功（不能看退出码）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if Handler.first_hit_at:
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def launch_window(url: str) -> None:
    """优先用原生窗口宿主；不可用时退回 Edge/Chrome 应用窗口，再不行用默认浏览器。"""
    data_dir = os.path.join(BASE, "data")
    host = os.path.join(BASE, "host", "dist", "ZzyangMonitor.exe")

    if os.path.exists(host):
        Handler.first_hit_at = 0.0
        log(f"启动原生窗口: {host} -> {url}")
        try:
            tray_mode = "tray" if zzsettings.load().get("close_to_tray") else "exit"
            proc = subprocess.Popen(
                [host, url, data_dir, tray_mode],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log(f"原生窗口启动失败：{e}")
            proc = None
        if proc is not None:
            if _wait_launched(proc):
                log("原生窗口已打开")
                try:
                    proc.wait()
                except KeyboardInterrupt:
                    pass
                log("原生窗口已关闭")
                return
            code = proc.poll()
            if code == 42:
                # 宿主发现已有窗口，把它叫到前台后退出。这是正常情况，不要退到浏览器。
                log("已有窗口，已切到前台")
                return
            log(f"原生窗口没有加载页面（退出码 {code}），改用浏览器窗口")
            try:
                proc.kill()
            except Exception:
                pass

    browser = find_browser()
    if not browser:
        import webbrowser

        log("没有找到 Edge/Chrome，改用默认浏览器")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    os.makedirs(PROFILE_DIR, exist_ok=True)
    args = [
        browser,
        f"--app={url}",
        f"--user-data-dir={PROFILE_DIR}",
        "--window-size=1240,860",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeSidebarV2,msImplicitSignin",
        "--disable-sync",
        "--disable-background-networking",
    ]
    Handler.first_hit_at = 0.0
    log(f"启动浏览器窗口: {browser} -> {url}")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if _wait_launched(proc):
            log("浏览器窗口已打开")
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
            log("浏览器窗口已关闭")
        else:
            log("浏览器窗口未能在 20 秒内加载页面，改用默认浏览器")
            import webbrowser

            webbrowser.open(url)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    finally:
        log("窗口进程结束")


def open_existing(port: int) -> None:
    """已经有实例在跑：只负责把窗口叫出来，不再起服务。"""
    url = f"http://127.0.0.1:{port}/"
    host = os.path.join(BASE, "host", "dist", "ZzyangMonitor.exe")
    if os.path.exists(host):
        try:
            subprocess.Popen([host, url, os.path.join(BASE, "data")]).wait()
            return
        except Exception as e:
            log(f"唤起已有窗口失败：{e}")
    import webbrowser

    webbrowser.open(url)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_server(port: int, timeout: float = 8.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.12)
    return False


def main() -> None:
    if "--check" in sys.argv:
        snap = botdata.build_snapshot()
        snap["stars"] = store.all_stars()
        snap["ok"] = True
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return

    if "--serve" not in sys.argv:
        # 单实例：已经有一个在跑，就把它叫到前面来，不再开第二个
        existing = read_instance()
        if existing:
            log(f"已有实例在 {existing}，直接打开它")
            open_existing(existing)
            return

    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"只读服务已启动: http://127.0.0.1:{port}/")
    if "--serve" not in sys.argv:
        write_instance(port)

    if "--serve" in sys.argv:
        print(f"http://127.0.0.1:{port}/", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    try:
        launch_window(f"http://127.0.0.1:{port}/")
    finally:
        server.shutdown()
        clear_instance()
        log("已退出")
        # 关窗就结束：不等守护线程，直接退出，避免残留进程
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)


if __name__ == "__main__":
    main()
