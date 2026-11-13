"""Uniform surface over the agent. The UI talks to this and nothing else.

Backed by the Node bridge, which owns the Letta Agent SDK session. This module
only translates bridge events into bus events and runs Python tools.
"""
import json
import threading

from . import events as E
from .bridge import Bridge
from .log import log


class Loop:
    def __init__(self, bus, cfg):
        self.bus = bus
        self.cfg = cfg
        self.mode = "letta"
        self._bridge = None
        self._pending = set()
        self._seen = {}
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------
    def start(self):
        self._bridge = Bridge(self.cfg, self._event)
        if self._bridge.start():
            return True
        self.bus.emit(E.ev(E.ERROR, text="bridge failed: %s" % self._bridge.error))
        return False

    def run(self, messages, model, platform_name="windows", max_steps=0, cfg=None):
        if cfg is not None:
            self.cfg = cfg
        if not self._bridge:
            return
        self._bridge.perm("standard" if self.cfg.get("confirm") else "unrestricted")
        last = next((m["content"] for m in reversed(messages)
                     if m.get("role") == "user"
                     and isinstance(m.get("content"), str)), "")
        if last:
            self._bridge.send(last)

    def restore(self):
        pass

    def release(self):
        if self._bridge:
            self._bridge.abort()

    def busy(self):
        return bool(self._pending)

    def approve(self, pid, ok):
        self._pending.discard(pid)
        if self._bridge:
            self._bridge.approve(pid, ok)

    def close(self):
        if self._bridge:
            self._bridge.close()

    # -- events --------------------------------------------------------
    def _delta(self, ident, full):
        """Bridge sends cumulative text per id; the UI wants only what is new."""
        with self._lock:
            before = self._seen.get(ident, 0)
            if len(full) <= before:
                return ""
            self._seen[ident] = len(full)
            return full[before:]

    def _event(self, kind, m):
        try:
            if kind == "text":
                new = self._delta(m.get("id") or "", m.get("text") or "")
                if new:
                    self.bus.emit(E.ev(E.DELTA, text=new))
            elif kind == "think":
                new = self._delta(m.get("id") or "", m.get("text") or "")
                if new:
                    self.bus.emit(E.ev(E.THINK, text=new))
            elif kind == "tool":
                self._tool(m)
            elif kind == "result":
                ok = m.get("ok")
                self.bus.emit(E.ev(E.TOOL_RESULT, ok=ok, text=m.get("text") or ""))
            elif kind == "approval":
                self._pending.add(m.get("id"))
                self.bus.emit(E.ev(E.CONFIRM, id=m.get("id"),
                                   name=m.get("name") or "tool", args=m.get("input") or {}))
            elif kind == "queue":
                self.bus.emit(E.ev(E.THINK, text="queued (%s)" % m.get("n")))
            elif kind == "done":
                self._pending.clear()
                self._seen.clear()
                if not m.get("ok"):
                    self.bus.emit(E.ev(E.ERROR, text="%s %s" % (m.get("code") or "",
                                                                m.get("stop") or "")))
                self.bus.emit(E.ev(E.TURN, messages=[]))
            elif kind == "error":
                self.bus.emit(E.ev(E.ERROR, text=m.get("text") or "bridge error"))
            elif kind == "agent":
                log("agent %s" % m.get("agent"))
            elif kind == "ready":
                log("bridge ready, conversation %s" % m.get("conversation"))
                if self.cfg.get("persona_stale"):
                    self.cfg["persona_stale"] = False
                    log("persona.md changed - set rebuild_agent to apply it")
            elif kind == "exit":
                self.bus.emit(E.ev(E.ERROR, text="bridge exited"))
            elif kind == "log":
                log("bridge: %s" % m.get("text"))
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
            bad = "error" in result
            if self._bridge:
                blob = json.dumps(result)
                if len(blob) > 24000:
                    blob = blob[:24000] + " ... [tool result truncated]"
                self._bridge.tool_result(ident, blob, bad)
        threading.Thread(target=work, daemon=True).start()