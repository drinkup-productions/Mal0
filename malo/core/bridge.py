"""Owns the Node bridge process. The only path from Python to the agent."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading

from . import config


def _find(name):
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        p = os.path.join(here, name)
        if os.path.isfile(p):
            return p
        here = os.path.dirname(here)
    return ""


BRIDGE = _find("bridge.mjs")
PERSONA = _find("persona.md")


def _hash(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except Exception:
        return ""


class Bridge:
    """Spawns bridge.mjs and pumps JSON lines. on_event(kind, payload) is required."""

    def __init__(self, cfg, on_event):
        self.cfg = cfg
        self.on_event = on_event
        self.proc = None
        self._lock = threading.Lock()
        self._tmp = []
        self.ready = threading.Event()
        self.error = ""
        self.conversation = ""

    # -- process -------------------------------------------------------
    def _node(self):
        exe = shutil.which("node")
        if not exe:
            raise RuntimeError("node not found on PATH - install Node 22.19+")
        return exe

    def _temp(self, data, suffix):
        fh = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False,
                                         encoding="utf-8")
        if isinstance(data, str):
            fh.write(data)
        else:
            json.dump(data, fh)
        fh.close()
        self._tmp.append(fh.name)
        return fh.name

    def _persona_arg(self):
        """A persona edit does not silently discard memory; it asks for a rebuild."""
        if PERSONA:
            digest = _hash(PERSONA)
            if digest and digest != self.cfg.get("persona_hash"):
                if self.cfg.get("letta_agent") and not self.cfg.get("rebuild_agent"):
                    self.cfg["persona_stale"] = True
                self.cfg["persona_hash"] = digest
            return ["--persona-file", PERSONA]
        if self.cfg.get("persona_text"):
            return ["--persona-file", self._temp(self.cfg["persona_text"], ".txt")]
        return []

    def _specs(self):
        from ..tools import registry
        allow = set(self.cfg.get("tool_allow") or [])
        specs = []
        for s in registry.all_specs():
            f = s.get("function") or {}
            name = f.get("name")
            if not name:
                continue
            if allow and name not in allow:
                continue
            specs.append({"name": name,
                          "label": name,
                          "description": f.get("description") or "",
                          "parameters": f.get("parameters") or
                          {"type": "object", "properties": {}}})
        return specs

    def _argv(self):
        if not BRIDGE:
            raise RuntimeError("bridge.mjs not found above malo/core")
        root = os.path.dirname(BRIDGE)
        argv = [self._node(), BRIDGE,
                "--url", self.cfg.get("letta_url") or "ws://127.0.0.1:4500",
                "--cwd", self.cfg.get("workspace") or os.getcwd(),
                "--perm", self.cfg.get("permission_mode") or "standard",
                "--mcp-file", self.cfg.get("mcp_file") or
                os.path.join(root, "mcp_servers.json"),
                "--tools-file", self._temp(self._specs(), ".json")]
        argv += self._persona_arg()
        if self.cfg.get("letta_agent") and not self.cfg.get("rebuild_agent"):
            argv += ["--agent", self.cfg["letta_agent"]]
        if self.cfg.get("letta_conversation") and not self.cfg.get("rebuild_agent"):
            argv += ["--conv", self.cfg["letta_conversation"]]
        return argv

    def start(self, timeout=90.0):
        try:
            self.proc = subprocess.Popen(
                self._argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1, cwd=os.path.dirname(BRIDGE))
        except Exception as exc:
            self.error = "%s: %s" % (type(exc).__name__, exc)
            return False
        threading.Thread(target=self._read, daemon=True, name="bridge-out").start()
        threading.Thread(target=self._drain, daemon=True, name="bridge-err").start()
        self._write({"cmd": "init"})
        self.ready.wait(timeout)
        return self.ready.is_set() and not self.error

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
                self._remember(msg)
                self.ready.set()
            elif ev == "error" and not self.ready.is_set():
                self.error = msg.get("text") or "bridge error"
                self.ready.set()
            self.on_event(ev, msg)
        if not self.ready.is_set():
            self.error = self.error or "bridge exited before ready"
            self.ready.set()
        self.on_event("exit", {})

    def _remember(self, msg):
        """Persist identity so a restart resumes instead of starting over."""
        changed = False
        agent = msg.get("agent")
        if agent and agent != self.cfg.get("letta_agent"):
            self.cfg["letta_agent"] = agent
            changed = True
        self.conversation = msg.get("conversation") or ""
        if self.conversation and self.conversation != self.cfg.get("letta_conversation"):
            self.cfg["letta_conversation"] = self.conversation
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
                self.error = str(exc)
                return False

    def send(self, text):
        return self._write({"cmd": "send", "text": text})

    def perm(self, mode):
        return self._write({"cmd": "perm", "mode": mode})

    def approve(self, ident, ok):
        return self._write({"cmd": "approve", "id": ident, "ok": bool(ok)})

    def tool_result(self, ident, text, error=False):
        return self._write({"cmd": "tool_result", "id": ident,
                            "text": text, "error": bool(error)})

    def abort(self):
        return self._write({"cmd": "abort"})

    def close(self):
        self._write({"cmd": "close"})
        if self.proc:
            try:
                self.proc.wait(5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        for path in self._tmp:
            try:
                os.unlink(path)
            except Exception:
                pass
        self._tmp.clear()