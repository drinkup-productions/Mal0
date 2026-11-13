"""UI-facing agent surface. Delegates to the supervised worker."""
import json
import threading

from . import events as E
from .log import log
from .workerproc import Worker


class Loop:
    def __init__(self, bus, cfg):
        self.bus = bus
        self.cfg = cfg
        self.mode = "letta"
        self._worker = None
        self._seen = {}

    def start(self):
        self._worker = Worker(self.cfg, self._event)
        if self._worker.start():
            return True
        self.bus.emit(E.ev(E.ERROR, text="worker failed to start"))
        return False

    def run(self, messages, model, platform_name="windows", max_steps=0, cfg=None):
        if cfg is not None:
            self.cfg = cfg
        if not self._worker:
            return
        self._worker.perm("standard" if self.cfg.get("confirm") else "unrestricted")
        last = next((m["content"] for m in reversed(messages)
                     if m.get("role") == "user"
                     and isinstance(m.get("content"), str)), "")
        if last:
            self._worker.send(last)

    def restore(self):
        pass

    def release(self):
        if self._worker:
            self._worker.abort()

    def busy(self):
        return bool(self._worker and self._worker.busy())

    def approve(self, pid, ok):
        if self._worker:
            self._worker.approve(pid, ok)

    def restart(self):
        if self._worker:
            self.bus.emit(E.ev(E.THINK, text="restarting worker"))
            return self._worker.restart()
        return False

    def alive(self):
        return bool(self._worker and self._worker.alive())

    def close(self):
        if self._worker:
            self._worker.close()

    # -- events --------------------------------------------------------
    def _delta(self, ident, full):
        before = self._seen.get(ident, 0)
        if len(full) <= before:
            return ""
        self._seen[ident] = len(full)
        return full[before:]

    def _event(self, kind, m):
        try:
            if kind in ("text", "think"):
                new = self._delta(m.get("id") or "", m.get("text") or "")
                if new:
                    self.bus.emit(E.ev(E.DELTA if kind == "text" else E.THINK,
                                       text=new))
            elif kind == "tool":
                self._tool(m)
            elif kind == "result":
                self.bus.emit(E.ev(E.TOOL_RESULT, ok=m.get("ok"),
                                   text=m.get("text") or ""))
            elif kind == "approval":
                self.bus.emit(E.ev(E.CONFIRM, id=m.get("id"),
                                   name=m.get("name") or "tool",
                                   args=m.get("input") or {}))
            elif kind == "queue":
                self.bus.emit(E.ev(E.THINK, text="queued (%s)" % m.get("n")))
            elif kind == "done":
                self._seen.clear()
                if not m.get("ok"):
                    self.bus.emit(E.ev(E.ERROR, text="%s %s" % (m.get("code") or "",
                                                                m.get("stop") or "")))
                self.bus.emit(E.ev(E.TURN, messages=[]))
            elif kind == "error":
                self.bus.emit(E.ev(E.ERROR, text=m.get("text") or "worker error"))
            elif kind == "dead":
                self.bus.emit(E.ev(E.ERROR, text="worker gave up - restart the app"))
            elif kind in ("ready", "agent", "log"):
                if kind == "log":
                    log("worker: %s" % m.get("text"))
        except Exception as exc:
            log("loop event %s: %s" % (kind, exc))

    def _tool(self, m):
        from ..tools import registry
        ident, name, args = m.get("id"), m.get("name") or "", m.get("input")
        if args is None:
            self.bus.emit(E.ev(E.TOOL, name=name, args={}))
            return
        if not ident:
            return
        self.bus.emit(E.ev(E.TOOL, name=name, args=args))

        def work():
            tmo = int(self.cfg.get("tool_timeout") or 120)
            result = {}
            try:
                done = [None, None]

                def call():
                    try:
                        done[0] = registry.run(name, args)
                    except Exception as exc:
                        done[1] = exc
                th = threading.Thread(target=call, daemon=True)
                th.start()
                th.join(tmo)
                if th.is_alive():
                    result = {"error": "tool timed out after %ds" % tmo}
                elif done[1]:
                    result = {"error": "%s: %s" % (type(done[1]).__name__, done[1])}
                else:
                    result = done[0] or {}
            except Exception as exc:
                result = {"error": "%s: %s" % (type(exc).__name__, exc)}
            blob = json.dumps(result)
            if len(blob) > 24000:
                blob = blob[:24000] + " ... [tool result truncated]"
            if self._worker:
                self._worker.tool_result(ident, blob, "error" in result)
        threading.Thread(target=work, daemon=True).start()