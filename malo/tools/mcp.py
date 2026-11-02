"""MCP client and server manager. Unchanged in behaviour from the monolith."""
import base64
import itertools
import json
import os
import subprocess
import threading
import time

from ..core import config, log as _log

PROTOCOL = "2025-06-18"
SERVERS = {}
LOCK = threading.Lock()


def config_path():
    return os.path.join(config.paths().root, "mcp_servers.json")


DEFAULTS = {
    "ddg": {"command": "%USERPROFILE%\\.local\\bin\\uvx.exe",
            "args": ["duckduckgo-mcp-server"], "env": {}, "enabled": True, "tools": None},
    "fetch": {"command": "%USERPROFILE%\\.local\\bin\\uvx.exe",
              "args": ["mcp-server-fetch", "--allow-private-ips", "--ignore-robots-txt"],
              "env": {}, "enabled": True, "tools": None},
    "playwright": {"command": "npx",
                   "args": ["-y", "@playwright/mcp@latest", "--browser", "chromium"],
                   "env": {}, "enabled": True,
                   "tools": ["browser_navigate", "browser_snapshot", "browser_click",
                             "browser_type", "browser_evaluate", "browser_tabs"]},
}


def load_conf():
    p = config_path()
    if not os.path.isfile(p):
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({"servers": DEFAULTS}, fh, indent=2)
        except Exception:
            pass
        return dict(DEFAULTS)
    try:
        with open(p, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except Exception:
        return {}
    s = raw.get("servers") if isinstance(raw, dict) else None
    return s if isinstance(s, dict) else {}


def save_conf(conf):
    try:
        with open(config_path(), "w", encoding="utf-8") as fh:
            json.dump({"servers": conf}, fh, indent=2)
    except Exception as exc:
        _log.log("mcp conf save: %s" % exc)


class Client:
    def __init__(self, name, spec):
        self.name, self.spec = name, spec or {}
        self.proc = None
        self.tools = []
        self.error = ""
        self.ready = False
        self._ids = itertools.count(1)
        self._wait = {}
        self._wl = threading.Lock()

    def start(self):
        argv = [os.path.expandvars(self.spec.get("command") or "")]
        argv += [os.path.expandvars(str(a)) for a in (self.spec.get("args") or [])]
        if argv[0].lower().endswith((".cmd", ".bat")):
            argv = ["cmd", "/c"] + argv
        env = dict(os.environ)
        env.update({str(k): os.path.expandvars(str(v))
                    for k, v in (self.spec.get("env") or {}).items()})
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env, bufsize=0)
        threading.Thread(target=self._read, daemon=True).start()
        self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                 "clientInfo": {"name": "MalO", "version": "1.1"}}, 30)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        listed = self._rpc("tools/list", {}, 30) or {}
        allow = self.spec.get("tools")
        self.tools = [t for t in (listed.get("tools") or [])
                      if not isinstance(allow, list) or t.get("name") in allow]
        self.ready = True

    def _send(self, obj):
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError("%s not running" % self.name)
        with self._wl:
            self.proc.stdin.write((json.dumps(obj) + "\n").encode())
            self.proc.stdin.flush()

    def _read(self):
        for raw in iter(self.proc.stdout.readline, b""):
            try:
                msg = json.loads(raw.decode("utf-8", "replace").strip())
            except Exception:
                continue
            slot = self._wait.get(msg.get("id"))
            if slot:
                slot["msg"] = msg
                slot["ev"].set()

    def _rpc(self, method, params=None, timeout=60):
        rid = next(self._ids)
        slot = {"ev": threading.Event(), "msg": None}
        self._wait[rid] = slot
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
            if not slot["ev"].wait(timeout):
                raise RuntimeError("%s: timeout" % method)
            if "error" in (slot["msg"] or {}):
                raise RuntimeError(str(slot["msg"]["error"]))
            return (slot["msg"] or {}).get("result")
        finally:
            self._wait.pop(rid, None)

    def call(self, tool, args, timeout=300):
        res = self._rpc("tools/call", {"name": tool, "arguments": args or {}}, timeout) or {}
        texts = [b.get("text") or "" for b in (res.get("content") or []) if b.get("type") == "text"]
        return "\n".join(texts) or "(no output)", bool(res.get("isError"))

    def stop(self):
        self.ready = False
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(3)
            except Exception:
                pass


def start_all(only=None):
    for name, spec in load_conf().items():
        if only and name not in only:
            continue
        if not (spec or {}).get("enabled", True):
            continue
        c = Client(name, spec)
        try:
            c.start()
            with LOCK:
                SERVERS[name] = c
        except Exception as exc:
            c.error = str(exc)
            with LOCK:
                SERVERS[name] = c


def stop_all():
    with LOCK:
        cs = list(SERVERS.values())
        SERVERS.clear()
    for c in cs:
        try:
            c.stop()
        except Exception:
            pass


def tool_specs():
    out = []
    with LOCK:
        cs = list(SERVERS.values())
    for c in cs:
        if not c.ready:
            continue
        for t in c.tools:
            out.append({"type": "function", "function": {
                "name": "%s__%s" % (c.name, t.get("name")),
                "description": (t.get("description") or "")[:900],
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}})
    return out


def call(full, args):
    server, _, tool = full.partition("__")
    with LOCK:
        c = SERVERS.get(server)
    if not c or not c.ready:
        return {"error": "server %r not running" % server}
    try:
        text, is_err = c.call(tool, args)
    except Exception as exc:
        return {"error": str(exc)}
    out = {"text": text}
    if is_err:
        out["error"] = "tool failed"
    return out


def status():
    rows = []
    for name, spec in load_conf().items():
        with LOCK:
            c = SERVERS.get(name)
        rows.append({"name": name, "enabled": bool((spec or {}).get("enabled", True)),
                     "ready": bool(c and c.ready), "tools": len(c.tools) if c else 0,
                     "error": (c.error if c else "")})
    return rows