"""Everything the UI is handed. Built once in __main__."""
import os

from . import config, events, log as _log, personas
from .log import log
from .. import platform as plat


class Runtime:
    def __init__(self):
        self.platform = plat.current()
        self.paths = self.platform.paths()
        _log.set_path(self.paths.log)
        for d in (self.paths.output, self.paths.personas_dir, self.paths.sfx_dir):
            os.makedirs(d, exist_ok=True)
        self.cfg = config.load()
        personas.load()
        self.bus = events.Bus()
        self.audio = self.platform.make_audio()
        self.app = None
        self.tray = None
        self.quitting = False

    def resolve_sfx(self, name):
        if not name:
            return None
        n = os.path.basename(str(name))
        for p in (os.path.join(self.paths.sfx_dir, n),
                  self.platform.asset(os.path.join("sfx", n)),
                  self.platform.asset(n)):
            if p and os.path.isfile(p):
                return p
        return None

    def play_sfx(self, name):
        if not name or not self.cfg.get("sfx", True):
            return
        p = self.resolve_sfx(name)
        if not p:
            log("sfx missing: %s" % name)
            return
        self.audio.play(p, int(self.cfg.get("sfx_volume") or 80))

    def run_shell(self, command, cwd=None, timeout=180):
        return self.platform.run_shell(command, cwd=cwd, timeout=timeout)