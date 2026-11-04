"""Uniform surface over the local engine and the Letta loop.

The UI talks to this and nothing else, so switching backends is one config key.
"""
from . import engine, events as E


class Loop:
    def __init__(self, bus, cfg):
        self.bus = bus
        self.cfg = cfg
        self.mode = "letta" if cfg.get("letta") else "engine"
        self._engine = None
        self._chat = None
        if self.mode == "letta":
            from . import letta
            self._chat = letta.Chat(bus, cfg)

    def start(self):
        if self.mode == "letta":
            if self._chat.start():
                return True
            self.bus.emit(E.ev(E.ERROR,
                               text="letta unreachable - falling back to the local engine"))
            self.mode = "engine"
            self._chat = None
        return True

    def run(self, messages, model, platform_name="windows", max_steps=0, cfg=None):
        if self.mode == "letta":
            if cfg is not None:
                self._chat.cfg = cfg
            last = next((m["content"] for m in reversed(messages)
                         if m.get("role") == "user"
                         and isinstance(m.get("content"), str)), "")
            if last:
                self._chat.send(last)
            return
        self._engine = engine.Engine(self.bus, cfg or self.cfg)
        self._engine.run(messages, model, platform_name, max_steps=max_steps)

    def restore(self):
        """Put the chat back on the live config after a wake override."""
        if self.mode == "letta" and self._chat:
            self._chat.cfg = self.cfg

    def release(self):
        if self.mode == "letta":
            if self._chat:
                self._chat.stop_turn()
        elif self._engine:
            self._engine.release()

    def approve(self, pid, ok):
        if self.mode == "letta":
            if self._chat:
                self._chat.approve(pid, ok)
        elif self._engine:
            self._engine.approve(pid, ok)

    def close(self):
        if self._chat:
            self._chat.close()