"""Idle-triggered wakes. Fires only when enabled, idle, cooled down and under cap."""
import threading
import time

from ..platform import current
from . import events as E
from . import log as _log

DEFAULT_BRIEF = ("Check whether anything on this machine needs attention: a stuck build, "
                 "a download finished, an error left in the log. If nothing does, do nothing.")
                 
SELFDEV_BRIEF = ("Improve your own source. Read code with code_grep first, pick ONE concrete "
                 "improvement - a bug, an unguarded edge, a rough corner - and write it as a "
                 "proposal with full file contents. Run the tests. One change only, then stop.")

class Waker:
    def __init__(self, bus, cfg, trigger, kind="idle"):
        self.kind = kind
        self.bus = bus
        self.cfg = cfg
        self.trigger = trigger
        self.stop = threading.Event()
        self.last = 0.0
        self.count = 0
        self.day = time.strftime("%Y-%m-%d")

    def _roll_day(self):
        today = time.strftime("%Y-%m-%d")
        if today != self.day:
            self.day = today
            self.count = 0

    def run(self):
        plat = current()
        while not self.stop.wait(30):
            try:
                if not self.cfg.get("autonomy", False):
                    continue
                self._roll_day()
                if self.count >= int(self.cfg.get("autonomy_max_per_day") or 12):
                    continue
                idle = plat.idle_seconds()
                if idle < int(self.cfg.get("autonomy_idle_secs") or 600):
                    continue
                if time.time() - self.last < int(self.cfg.get("autonomy_cooldown_secs") or 1800):
                    continue
                self.last = time.time()
                self.count += 1
                self.bus.emit(E.ev(E.WAKE, idle=int(idle), count=self.count))
                self.trigger(self.kind, reason)
            except Exception as exc:
                _log.log("autonomy: %s" % exc)

    def start(self):
        threading.Thread(target=self.run, daemon=True, name="autonomy").start()
        return self

    def halt(self):
        self.stop.set()
        
        
class SelfDevWaker(Waker):
    def __init__(self, bus, cfg, trigger):
        super().__init__(bus, cfg, trigger, kind="selfdev")

    def run(self):
        plat = current()
        while not self.stop.wait(60):
            try:
                if self.cfg.get("self_edit") not in ("propose", "apply"):
                    continue
                self._roll_day()
                if self.count >= int(self.cfg.get("selfdev_max_per_day") or 6):
                    continue
                if plat.idle_seconds() < int(self.cfg.get("selfdev_idle_secs") or 1800):
                    continue
                if time.time() - self.last < int(self.cfg.get("selfdev_cooldown_secs") or 3600):
                    continue
                self.last = time.time()
                self.count += 1
                self.bus.emit(E.ev(E.WAKE, idle=int(plat.idle_seconds()), count=self.count))
                self.trigger("selfdev", "idle self-development, %d today" % self.count)
            except Exception as exc:
                _log.log("selfdev: %s" % exc)