"""Android adapter. Runs under Kivy + python-for-android.

Perception (screens/windows/idle) falls back to the base defaults: there is no
desktop surface. Shell is /system/bin/sh. Notifications go through plyer.
App launching goes through am start.
"""
import os
import subprocess

from .base import Audio, Paths, Platform


def _run(argv, timeout=20):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:
        return 1, "", str(exc)


class PlyerAudio(Audio):
    backend = "plyer"

    def play(self, path, volume=80):
        try:
            from plyer import audio
            audio.play(path)
            return True
        except Exception:
            return False

    def stop_all(self):
        try:
            from plyer import audio
            audio.stop()
        except Exception:
            pass


class Android(Platform):
    name = "android"
    has_tray = False

    def _root(self):
        base = os.environ.get("ANDROID_PRIVATE") or os.environ.get("HOME") or "."
        d = os.path.join(base, "malo")
        os.makedirs(d, exist_ok=True)
        return d

    def paths(self):
        root = self._root()
        return Paths(root, os.path.join(root, "config.json"), os.path.join(root, "output"),
                     os.path.join(root, "malo.log"), os.path.join(root, "feedback.jsonl"),
                     os.path.join(root, "personas.json"), os.path.join(root, "personas"),
                     os.path.join(root, "sfx"),
                     os.environ.get("EXTERNAL_STORAGE") or root)

    def asset(self, name):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "assets", name)
        return p if os.path.isfile(p) else None

    def run_shell(self, command, cwd=None, timeout=180):
        r = subprocess.run(["/system/bin/sh", "-c", command], cwd=cwd,
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout, r.stderr

    def make_audio(self):
        return PlyerAudio()

    def open_path(self, path):
        _run(["am", "start", "-a", "android.intent.action.VIEW", "-d", "file://" + path])

    def _resolve_package(self, needle):
        code, out, _ = _run(["pm", "list", "packages"])
        n = needle.lower()
        for ln in out.splitlines():
            pkg = ln.replace("package:", "").strip()
            if n in pkg.lower():
                return pkg
        return None

    def open_app(self, package):
        package = str(package or "")
        if "." not in package:
            package = self._resolve_package(package)
            if not package:
                return False
        code, out, err = _run(["monkey", "-p", package, "-c",
                               "android.intent.category.LAUNCHER", "1"])
        return code == 0

    def list_apps(self, limit=120):
        code, out, _ = _run(["pm", "list", "packages", "-3"])
        rows = [ln.replace("package:", "").strip() for ln in out.splitlines() if ln.strip()]
        return sorted(rows)[:limit]

    def notify(self, title, text):
        try:
            from plyer import notification
            notification.notify(title=str(title)[:60], message=str(text)[:200], timeout=6)
            return True
        except Exception:
            return False