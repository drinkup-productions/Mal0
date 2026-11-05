import os
import shutil
import subprocess
import sys

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