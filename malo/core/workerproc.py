"""Supervises the worker process. Same public surface the UI already uses."""
import json
import os
import subprocess
import sys
import threading
import time

from . import config, events as E
from .log import log

BACKOFF = (1, 2, 4, 8, 16)
MAX_TRIES = 5


class Worker:
    def __init__(self, cfg, on_event):
        self.cfg = cfg
        self.on_event = on_event
        self.proc = None
        self._lock = threading.Lock()
        self._tries = 0
        self._intentional = False
        self._stopping = False
        self._ready = threading.Event()
        self._seen = {}
        self._pending = set()

    # -- process -------------------------------------------------------
    def _argv(self):
        from ..tools import registry
        allow = set(self.cfg.get("tool_allow") or [])
        specs = []
        for s in registry.all_specs():
            f = s.get("function") or {}
            name = f.get("name")
            if not name or (allow and name not in allow):
                continue
            specs.append({"name": name, "label": name,
                          "description": f.get("description") or "",
                          "parameters": f.get("parameters") or
                          {"type": "object", "properties": {}}})
        argv = [sys.executable, "-m", "malo.worker",
                "--url", self.cfg.get("letta_url") or "ws://127.0.0.1:4500",
                "--cwd", self.cfg.get("workspace") or os.getcwd(),
                "--perm", self.cfg.get("permission_mode") or "standard",
                "--model", self.cfg.get("letta_model") or "",
                "--mcp-file", self.cfg.get("mcp_file") or "",
                "--tools-file", self._temp(specs)]
        from .bridge import _find
        persona = self.cfg.get("persona_file") or _find("persona.md")
        if persona:
            argv += ["--persona-file", persona]
        if self.cfg.get("letta_agent"):
            argv += ["--agent", self.cfg["letta_agent"]]
        if self.cfg.get("letta_conversation"):
            argv += ["--conv", self.cfg["letta_conversation"]]
        return argv

    def _temp(self, specs):
        import tempfile
        fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
        json.dump(specs, fh)
        fh.close()
        return fh.name

    def start(self, timeout=90.0):
        self._intentional = False
        self._ready.clear()
        try:
            self.proc = subprocess.Popen(
                self._argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except Exception as exc:
            self.on_event("error", {"text": "worker spawn: %s: %s"
                                    % (type(exc).__name__, exc)})
            return False
        threading.Thread(target=self._read, daemon=True, name="worker-out").start()
        threading.Thread(target=self._drain, daemon=True, name="worker-err").start()
        self._ready.wait(timeout)
        return self._ready.is_set() and not self._stopping

    def _drain(self):
        for line in self.proc.stderr:
            self.on_event("log", {"text": line.rstrip()})

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                self.on_event("log", {"text": line[:400]})
                continue
            ev = msg.get("ev") or "log"
            if ev == "ready":
                self._tries = 0
                self._remember(msg)
                self._ready.set()
            self.on_event(ev, msg)
        code = self.proc.poll() if self.proc else None
        if not self._ready.is_set():
            self._ready.set()
        if self._stopping:
            return
        if self._intentional:
            log("worker restart requested")
            self._intentional = False
            self._spawn_again(0)
            return
        self._tries += 1
        if self._tries > MAX_TRIES:
            self.on_event("error", {"text": "worker died %d times, giving up"
                                    % (self._tries - 1)})
            self.on_event("dead", {})
            return
        delay = BACKOFF[min(self._tries - 1, len(BACKOFF) - 1)]
        self.on_event("error", {"text": "worker exited (%s), retry %d in %ds"
                                % (code, self._tries, delay)})
        self._spawn_again(delay)

    def _spawn_again(self, delay):
        def go():
            if delay:
                time.sleep(delay)
            if self._stopping:
                return
            self.start()
        threading.Thread(target=go, daemon=True, name="worker-restart").start()

    def _remember(self, msg):
        changed = False
        for key, field in (("letta_agent", "agent"),
                           ("letta_conversation", "conversation")):
            val = msg.get(field)
            if val and val != self.cfg.get(key):
                self.cfg[key] = val
                changed = True
        if self.cfg.get("rebuild_agent"):
            self.cfg["rebuild_agent"] = False
            changed = True
        if changed:
            config.save()

    # -- commands ------------------------------------------------------
    def _write(self, obj):
        if not self.proc or self.proc.poll() is not None:
            return False
        with self._lock:
            try:
                self.proc.stdin.write(json.dumps(obj) + "\n")
                self.proc.stdin.flush()
                return True
            except Exception as exc:
                log("worker write: %s" % exc)
                return False

    def send(self, text):
        return self._write({"cmd": "send", "text": text})

    def perm(self, mode):
        return self._write({"cmd": "perm", "mode": mode})

    def approve(self, ident, ok):
        self._pending.discard(ident)
        return self._write({"cmd": "approve", "id": ident, "ok": bool(ok)})

    def tool_result(self, ident, text, error=False):
        return self._write({"cmd": "tool_result", "id": ident,
                            "text": text, "error": bool(error)})

    def abort(self):
        return self._write({"cmd": "abort"})

    def busy(self):
        return bool(self._pending)

    def restart(self):
        if not self.proc:
            return False
        self._intentional = True
        self._pending.clear()
        self._seen.clear()
        try:
            self.proc.terminate()
        except Exception:
            pass
        return True

    def alive(self):
        return bool(self.proc and self.proc.poll() is None)

    def close(self):
        self._stopping = True
        self._write({"cmd": "stop"})
        if self.proc:
            try:
                self.proc.wait(5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass