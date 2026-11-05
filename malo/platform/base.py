"""The only surface core/ is allowed to touch the outside world through."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Paths:
    root: str
    config: str
    output: str
    log: str
    feedback: str
    personas: str
    personas_dir: str
    sfx_dir: str
    workspace_default: str

    def asset(self, name):
        from . import current
        return current().asset(name)


class Audio(ABC):
    backend = "none"

    @abstractmethod
    def play(self, path, volume=80): ...

    def stop_all(self): ...


class Tray(ABC):
    @abstractmethod
    def run(self, app): ...

    def stop(self): ...

    def set_text(self, text): ...


class Platform(ABC):
    name = "generic"
    has_tray = False

    @abstractmethod
    def paths(self) -> Paths: ...

    @abstractmethod
    def asset(self, name): ...

    def screens(self):
        """[{"index":0,"left":0,"top":0,"width":1920,"height":1080}]"""
        return []

    def grab(self, region=None):
        """PIL image of the whole desktop or an (l,t,r,b) region, or None."""
        return None

    def windows(self, limit=60):
        """[{"hwnd":int,"title":str,"proc":str}] visible top-level windows."""
        return []

    def focus_window(self, hwnd):
        return False

    def idle_seconds(self):
        return 0.0

    def set_notify(self, fn):
        self._notify = fn

    def notify(self, title, text):
        fn = getattr(self, "_notify", None)
        if not fn:
            return False
        try:
            fn(title, text)
            return True
        except Exception:
            return False

    @abstractmethod
    def run_shell(self, command, cwd=None, timeout=180):
        """Return (exit_code, stdout, stderr)."""

    @abstractmethod
    def make_audio(self) -> Audio: ...

    def make_tray(self):
        return None

    def open_path(self, path):
        raise NotImplementedError

    def spawn_flags(self):
        return 0

    def short_path(self, path):
        return path