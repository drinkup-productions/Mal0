import os
import shutil
import subprocess
import sys
import tempfile

from .base import Audio, Paths, Platform


class ProcAudio(Audio):
    def __init__(self):
        self._player = ""
        for exe in ("ffplay", "mpv", "afplay", "paplay", "aplay"):
            p = shutil.which(exe)
            if p:
                self._player = p
                break
        self.backend = os.path.basename(self._player) if self._player else "none"

    def play(self, path, volume=80):
        if not self._player:
            return False
        cmd = [self._player]
        if self._player.endswith("ffplay"):
            cmd += ["-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", str(volume)]
        elif self._player.endswith("mpv"):
            cmd += ["--no-video", "--really-quiet", "--volume=%d" % volume]
        cmd.append(path)
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False


class Posix(Platform):
    name = "posix"

    def paths(self):
        root = os.environ.get("MALO_DATA") or os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MalOAvatar")
        os.makedirs(root, exist_ok=True)
        return Paths(root, os.path.join(root, "config.json"), os.path.join(root, "output"),
                     os.path.join(root, "malo.log"), os.path.join(root, "feedback.jsonl"),
                     os.path.join(root, "personas.json"), os.path.join(root, "personas"),
                     os.path.join(root, "sfx"), os.path.expanduser("~"))

    def asset(self, name):
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        p = os.path.join(here, "assets", name)
        return p if os.path.isfile(p) else None

    def run_shell(self, command, cwd=None, timeout=180):
        r = subprocess.run(["/bin/sh", "-c", command], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return r.returncode, r.stdout, r.stderr

    def make_audio(self):
        return ProcAudio()

    def open_path(self, path):
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, path])

    # -- desktop control ----------------------------------------------------
    # Wayland and X11 use different tooling; pick what exists at call time so
    # one implementation serves both. Missing tools degrade to False/[] rather
    # than raising, so the tools report failure cleanly instead of crashing.

    def __init__(self):
        self._last_capture_size = None  # (w, h) from the last successful grab

    def _bin(self, *names):
        for n in names:
            p = shutil.which(n)
            if p:
                return p
        return None

    def _run_cli(self, cmd, timeout=15):
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout)
            return True
        except Exception:
            return False

    def _pick_input(self):
        """(binary, is_wayland_backend), or (None, False). ydotool injects via
        /dev/uinput and works on Wayland; xdotool only reaches X11/XWayland
        clients. Prefer the backend matching the session."""
        if os.environ.get("WAYLAND_DISPLAY"):
            b = self._bin("ydotool")
            if b:
                return b, True
            b = self._bin("xdotool")  # best effort: XWayland clients only
            if b:
                return b, False
        elif os.environ.get("DISPLAY"):
            b = self._bin("xdotool")
            if b:
                return b, False
        return None, False

    def _move(self, tool, is_yd, x, y):
        cmd = [tool] + (["mousemove", "--absolute"] if is_yd else ["mousemove"]) \
            + [str(int(x)), str(int(y))]
        return self._run_cli(cmd)

    def mouse_move(self, x, y):
        tool, is_yd = self._pick_input()
        return self._move(tool, is_yd, x, y) if tool else False

    def mouse_click(self, x=None, y=None, button="left", double=False):
        tool, is_yd = self._pick_input()
        if not tool:
            return False
        btn = {"left": 1, "middle": 2, "right": 3}.get(str(button or "left").lower(), 1)
        ok = True
        if x is not None and y is not None:
            ok = self._move(tool, is_yd, x, y)
        for _ in range(2 if double else 1):
            ok = self._run_cli([tool, "click", str(btn)]) and ok
        return ok

    def mouse_scroll(self, amount=3):
        tool, _ = self._pick_input()
        if not tool:
            return False
        btn = "4" if int(amount or 0) > 0 else "5"  # wheel up/down button numbers
        ok = True
        for _ in range(abs(int(amount or 0))):
            ok = self._run_cli([tool, "click", btn]) and ok
        return ok

    def key_press(self, keys):
        tool, _ = self._pick_input()
        if not tool:
            return False
        # both backends take modifier+key combos in xdotool's ctrl+s syntax
        return self._run_cli([tool, "key", str(keys or "")])

    def type_text(self, text):
        tool, is_yd = self._pick_input()
        if not tool:
            return False
        cmd = [tool, "type"] \
            + (["--delay", "20"] if is_yd else ["--clearmodifiers", "--delay", "20"]) \
            + [str(text or "")]
        return self._run_cli(cmd)

    def screens(self):
        """[{"index": 0, ...}] sized from the last capture. Wayland compositors
        expose no stable CLI for output geometry."""
        s = self._last_capture_size
        if not s:
            return []
        return [{"index": 0, "left": 0, "top": 0,
                 "width": int(s[0]), "height": int(s[1])}]

    def grab(self, region=None):
        img = self._capture_output()
        if img is None:
            return None
        l, t, r, b = (int(v) for v in (region or (0, 0, img.width, img.height)))
        try:
            img = img.crop((l, t, min(r, img.width), min(b, img.height)))
        except Exception:
            pass
        return img

    def _capture_output(self):
        """Full-output screenshot as a PIL Image, or None. KDE (Wayland or X11)
        via spectacle, wlroots compositors via grim, plain X11 via scrot."""
        try:
            from PIL import Image
        except Exception:
            return None
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        if self._bin("spectacle"):
            ok = self._run_cli(["spectacle", "-b", "-n", "-o", tmp])
        elif os.environ.get("WAYLAND_DISPLAY") and self._bin("grim"):
            ok = self._run_cli(["grim", tmp])
        else:
            b = self._bin("scrot")
            ok = self._run_cli([b, tmp]) if b else False
        if not ok or not os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return None
        try:
            img = Image.open(tmp).convert("RGB")
            self._last_capture_size = (img.width, img.height)
            return img
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def windows(self, limit=60):
        """X11 only (xdotool). No clean CLI lists Wayland windows."""
        tool, is_yd = self._pick_input()
        if not tool or is_yd:
            return []
        try:
            r = subprocess.run([tool, "search", "--onlyvisible", ""],
                               capture_output=True, text=True, timeout=10)
        except Exception:
            return []
        out = []
        for wid in (r.stdout or "").split()[:int(limit or 60)]:
            try:
                t = subprocess.run([tool, "getwindowname", wid],
                                   capture_output=True, text=True, timeout=5)
                title = (t.stdout or "").strip().replace("\n", " ")
            except Exception:
                title = ""
            out.append({"hwnd": int(wid), "title": title, "proc": ""})
        return out

    def focus_window(self, hwnd):
        tool, is_yd = self._pick_input()
        if not tool or is_yd:
            return False
        try:
            return bool(self._run_cli([tool, "windowactivate", str(int(hwnd))]))
        except Exception:
            return False

    def notify(self, title, text):
        if super().notify(title, text):  # prefer the in-app callback first
            return True
        b = self._bin("notify-send")
        if not b:
            return False
        try:
            subprocess.Popen([b, str(title), str(text)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False