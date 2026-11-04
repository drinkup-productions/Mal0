import ctypes
import itertools
import os
import shutil
import subprocess
import sys
import threading
from ctypes import wintypes

from ..core.log import log
from .base import Audio, Paths, Platform

NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _short(path):
    try:
        buf = ctypes.create_unicode_buffer(600)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 600)
        return buf.value if n else path
    except Exception:
        return path


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class MciAudio(Audio):
    def __init__(self):
        self._mci = None
        self._live = {}
        self._lock = threading.Lock()
        self._n = itertools.count(1)
        try:
            fn = ctypes.WinDLL("winmm").mciSendStringW
            fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HWND]
            fn.restype = wintypes.UINT
            self._mci = fn
            self.backend = "mci"
        except Exception as exc:
            log("mci unavailable: %s" % exc)
            self.backend = "none"

    def _cmd(self, cmd, buf=None):
        try:
            return self._mci(cmd, buf, len(buf) if buf is not None else 0, None)
        except Exception:
            return 1

    def play(self, path, volume=80):
        if self._mci is None:
            return False
        alias = "m%d" % next(self._n)
        sp = _short(path)
        with self._lock:
            if self._cmd('open "%s" type mpegvideo alias %s' % (sp, alias)):
                if self._cmd('open "%s" alias %s' % (sp, alias)):
                    return False
            self._cmd("setaudio %s volume to %d" % (alias, int(volume * 10)))
            if self._cmd("play %s" % alias):
                self._cmd("close %s" % alias)
                return False
            self._live[alias] = True
        return True

    def stop_all(self):
        if self._mci is None:
            return
        with self._lock:
            for a in list(self._live):
                self._cmd("close %s" % a)
            self._live.clear()

    def reap(self):
        if self._mci is None:
            return
        buf = ctypes.create_unicode_buffer(32)
        for a in list(self._live):
            with self._lock:
                if a not in self._live:
                    continue
                buf.value = ""
                self._cmd("status %s mode" % a, buf)
                if buf.value != "playing":
                    self._cmd("close %s" % a)
                    self._live.pop(a, None)


class Windows(Platform):
    name = "windows"
    has_tray = True

    def paths(self):
        root = os.environ.get("MALO_DATA") or os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MalOAvatar")
        os.makedirs(root, exist_ok=True)
        return Paths(
            root=root,
            config=os.path.join(root, "config.json"),
            output=os.path.join(root, "output"),
            log=os.path.join(root, "malo.log"),
            feedback=os.path.join(root, "feedback.jsonl"),
            personas=os.path.join(root, "personas.json"),
            personas_dir=os.path.join(root, "personas"),
            sfx_dir=os.path.join(root, "sfx"),
            workspace_default=os.path.expanduser("~"),
        )

    def notify(self, title, text):
        try:
            from win11toast import toast
            toast(str(title)[:60], str(text)[:200])
            return True
        except Exception:
            return super().notify(title, text)

    def asset(self, name):
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        p = os.path.join(here, "assets", name)
        if os.path.isfile(p):
            return p
        base = getattr(sys, "_MEIPASS", None)
        if base and os.path.isfile(os.path.join(base, name)):
            return os.path.join(base, name)
        return None

    def run_shell(self, command, cwd=None, timeout=180):
        cmd = (command or "").replace("&&", ";")
        prefix = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
                  "$OutputEncoding=[System.Text.Encoding]::UTF8;")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + cmd],
            cwd=cwd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=NO_WIN)
        return r.returncode, r.stdout, r.stderr

    def make_audio(self):
        return MciAudio()

    def open_path(self, path):
        os.startfile(path)

    def spawn_flags(self):
        return NO_WIN

    def short_path(self, path):
        return _short(path)

    def screens(self):
        out = []
        user32 = ctypes.windll.user32
        proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                                  ctypes.POINTER(RECT), ctypes.c_double)

        def _cb(hmon, hdc, lprc, data):
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                r = mi.rcMonitor
                out.append({"index": len(out), "left": r.left, "top": r.top,
                            "width": r.right - r.left, "height": r.bottom - r.top})
            return 1

        user32.EnumDisplayMonitors(None, None, proc(_cb), 0)
        return out

    def grab(self, region=None):
        from PIL import ImageGrab
        if region:
            return ImageGrab.grab(bbox=tuple(region), all_screens=True)
        return ImageGrab.grab(all_screens=True)

    def windows(self, limit=60):
        out = []
        seen = set()
        user32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def _name(pid):
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(260)
                size = ctypes.c_ulong(260)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    return os.path.basename(buf.value)
                return ""
            finally:
                k32.CloseHandle(h)

        def _cb(hwnd, data):
            if len(out) >= limit:
                return 0
            if not user32.IsWindowVisible(hwnd):
                return 1
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return 1
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = _name(pid.value)
            key = buf.value.lower()
            if key in seen:
                return 1
            seen.add(key)
            out.append({"hwnd": int(hwnd), "title": buf.value, "proc": name})
            return 1

        user32.EnumWindows(proc(_cb), 0)
        return out

    def focus_window(self, hwnd):
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        return bool(user32.SetForegroundWindow(hwnd))

    def idle_seconds(self):
        li = LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            return 0.0
        k32 = ctypes.windll.kernel32
        k32.GetTickCount.restype = wintypes.DWORD
        return max(0.0, ((k32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0)

    # ---- input -------------------------------------------------------
    def _vk(self, name):
        n = str(name).lower()
        table = {"enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
                 "space": 0x20, "backspace": 0x08, "delete": 0x2E,
                 "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
                 "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
                 "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
        if n in table:
            return table[n]
        if len(n) == 1:
            return ctypes.windll.user32.VkKeyScanW(ord(n.upper())) & 0xFF
        return None

    def mouse_move(self, x, y):
        return bool(ctypes.windll.user32.SetCursorPos(int(x), int(y)))

    def mouse_click(self, x=None, y=None, button="left", double=False):
        u32 = ctypes.windll.user32
        if x is not None and y is not None:
            u32.SetCursorPos(int(x), int(y))
        pair = {"right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}.get(
            str(button).lower(), (0x0002, 0x0004))
        for _ in range(2 if double else 1):
            u32.mouse_event(pair[0], 0, 0, 0, 0)
            u32.mouse_event(pair[1], 0, 0, 0, 0)
        return True

    def mouse_scroll(self, amount):
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(amount) * 120, 0)
        return True

    def key_press(self, keys):
        u32 = ctypes.windll.user32
        codes = [self._vk(k) for k in str(keys).replace("+", " ").split()]
        codes = [c for c in codes if c]
        if not codes:
            return False
        for c in codes:
            u32.keybd_event(c, 0, 0, 0)
        for c in reversed(codes):
            u32.keybd_event(c, 0, 0x0002, 0)
        return True

    def type_text(self, text):
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        buf = ctypes.create_unicode_buffer(str(text))
        size = ctypes.sizeof(buf)
        u32.OpenClipboard(None)
        try:
            u32.EmptyClipboard()
            h = k32.GlobalAlloc(0x0042, size)
            p = k32.GlobalLock(h)
            ctypes.memmove(p, buf, size)
            k32.GlobalUnlock(h)
            u32.SetClipboardData(13, h)
        finally:
            u32.CloseClipboard()
        u32.keybd_event(0x11, 0, 0, 0)
        u32.keybd_event(0x56, 0, 0, 0)
        u32.keybd_event(0x56, 0, 0x0002, 0)
        u32.keybd_event(0x11, 0, 0x0002, 0)
        return True

    def make_tray(self):
        return PystrayTray()


class PystrayTray:
    def __init__(self):
        self._icon = None

    def run(self, app):
        try:
            import pystray
        except Exception as exc:
            log("tray unavailable: %s" % exc)
            return
        from ..core import config, personas

        menu = pystray.Menu(
            pystray.MenuItem("Open MalO", app.show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Persona", pystray.Menu(*[
                pystray.MenuItem(p["label"],
                                 (lambda pid: lambda: app.root.after(0, app._set_persona, pid))(pid),
                                 checked=(lambda pid: lambda i: personas.active(app.cfg) == pid)(pid),
                                 radio=True)
                for pid, p in personas.PERSONAS.items()])),
            pystray.MenuItem("Ask before write / edit / bash",
                             lambda: (app.cfg.__setitem__("confirm", not app.cfg.get("confirm")),
                                      config.save()),
                             checked=lambda i: bool(app.cfg.get("confirm"))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", app.quit),
        )
        self._icon = pystray.Icon("MalO", _icon_image(app), "MalO", menu)
        try:
            from . import current
            current().set_notify(lambda t, x: self._icon.notify(x, t))
        except Exception:
            pass
        self._icon.run()

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def set_text(self, text):
        if self._icon:
            try:
                self._icon.title = "MalO - " + text
            except Exception:
                pass


def _icon_image(app):
    from PIL import Image, ImageDraw
    from ..core import personas
    p = personas.base_image(personas.active(app.cfg))
    if p:
        try:
            im = Image.open(p).convert("RGBA")
            w, h = im.size
            head = im.crop((int(w * .3), 0, int(w * .72), int(h * .36)))
            s = max(head.size)
            c = Image.new("RGBA", (s, s), (0, 0, 0, 0))
            c.paste(head, ((s - head.width) // 2, (s - head.height) // 2), head)
            return c.resize((64, 64), Image.LANCZOS)
        except Exception:
            pass
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((2, 2, 62, 62), fill=(139, 92, 246, 255))
    return im