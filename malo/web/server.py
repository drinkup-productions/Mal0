"""Web front end. Same Engine and Bus as the desktop UI, over SSE + POST."""
import hmac
import json
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..core import (config, engine, events as E, feedback, personas, profiles,
                    provider)
from ..core.log import log
from .page import PAGE

CLIENTS = []
LOCK = threading.Lock()
S = {"rt": None, "eng": None, "streaming": False, "pend": None,
     "stage": 0, "history": [], "last_user": "", "last_bot": ""}


def broadcast(ev):
    with LOCK:
        for q in list(CLIENTS):
            q.put(ev)


def pump(bus):
    while True:
        bus.drain(_handle)
        threading.Event().wait(0.05)


def _handle(ev):
    t = ev.get("type")
    if t == E.DELTA:
        broadcast(ev)
        return
    if t == E.CONFIRM:
        S["pend"] = ev["id"]
        broadcast(ev)
        return
    if t == E.TURN:
        for m in ev.get("messages") or []:
            if m.get("role") != "system":
                S["history"].append(m)
        while len(S["history"]) > 60:
            S["history"].pop(0)
        S["streaming"] = False
        broadcast(ev)
        return
    broadcast(ev)


def _token():
    tok = config.CFG.get("web_token")
    if not tok:
        tok = secrets.token_urlsafe(24)
        config.CFG["web_token"] = tok
        config.save()
    return tok


def _personas_brief():
    return [{"id": p["id"], "label": p["label"]} for p in personas.brief()]


def _treat_spec():
    return (personas.PERSONAS.get(personas.active(config.CFG)) or {}).get("treat") or {}


class Handler(BaseHTTPRequestHandler):
    server_version = "malo"

    def log_message(self, fmt, *a):
        pass

    def _authed(self, qs):
        sent = (qs.get("t") or [""])[0] or self.headers.get("X-Token", "")
        return hmac.compare_digest(sent, self.server.token)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._authed(qs):
            return self._json({"error": "bad token"}, 403)
        if u.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/state":
            return self._json({
                "personas": _personas_brief(),
                "models": self.server.models(),
                "active": personas.active(config.CFG),
                "model": config.CFG.get("model") or "",
                "stage": S["stage"],
                "streaming": S["streaming"],
                "profiles": [{"name": r["name"], "active": r["active"]}
                             for r in profiles.rows()],
                "profile": profiles.active_name(),
            })
        if u.path == "/img":
            name = (qs.get("name") or [""])[0]
            pid = personas.active(config.CFG)
            p = personas.asset(pid, name) if name else personas.base_image(pid)
            if not p:
                return self._json({"error": "no image"}, 404)
            with open(p, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == "/events":
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = queue.Queue()
            with LOCK:
                CLIENTS.append(q)
            try:
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        ev = q.get(timeout=20)
                        payload = b"data: " + json.dumps(ev).encode() + b"\n\n"
                    except queue.Empty:
                        payload = b": ping\n\n"
                    self.wfile.write(payload)
                    self.wfile.flush()
            except (ConnectionError, OSError):
                pass
            finally:
                with LOCK:
                    if q in CLIENTS:
                        CLIENTS.remove(q)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if not self._authed(parse_qs(u.query)):
            return self._json({"error": "bad token"}, 403)
        body = self._body()
        rt = S["rt"]
        if u.path == "/send":
            text = (body.get("text") or "").strip()
            model = config.CFG.get("model")
            if not text or S["streaming"] or not model:
                return self._json({"ok": False})
            S["history"].append({"role": "user", "content": text})
            S["last_user"], S["last_bot"] = text, ""
            S["streaming"] = True
            S["eng"] = engine.Engine(rt.bus, config.CFG)
            threading.Thread(target=S["eng"].run,
                             args=(list(S["history"]), model, rt.platform.name),
                             daemon=True).start()
            return self._json({"ok": True})
        if u.path == "/stop":
            if S["eng"]:
                S["eng"].release()
            return self._json({"ok": True})
        if u.path == "/confirm":
            if S["eng"] and S["pend"] is not None:
                S["eng"].approve(S["pend"], bool(body.get("ok")))
            S["pend"] = None
            return self._json({"ok": True})
        if u.path == "/persona":
            pid = body.get("id") or ""
            if pid not in personas.PERSONAS:
                return self._json({"ok": False})
            config.CFG["persona"] = pid
            want = (personas.PERSONAS.get(pid) or {}).get("model") or ""
            if want:
                config.CFG["model"] = want
            config.save()
            S["stage"] = 0
            S["history"] = []
            broadcast(E.ev(E.STATE))
            return self._json({"ok": True})
        if u.path == "/profile":
            r = profiles.use(body.get("name") or "")
            if "error" in r:
                return self._json({"ok": False, "error": r["error"]})
            S["history"] = []
            broadcast(E.ev(E.STATE))
            return self._json({"ok": True, "profile": r["profile"],
                               "workspace": r["workspace"]})
        if u.path == "/model":
            v = body.get("value") or ""
            if v:
                config.CFG["model"] = v
                config.save()
            return self._json({"ok": True})
        if u.path == "/pat":
            feedback.add("good", "", S["last_user"], S["last_bot"],
                         personas.active(config.CFG))
            rt.play_sfx(config.CFG.get("sfx_headpat"))
            rt.play_sfx(config.CFG.get("sfx_goodgirl"))
            return self._json({"ok": True})
        if u.path == "/treat":
            stages = _treat_spec().get("stages") or []
            if not stages:
                return self._json({"stage": 0})
            S["stage"] = min(S["stage"] + 1, len(stages))
            rt.play_sfx(config.CFG.get("sfx_treat"))
            return self._json({"stage": S["stage"]})
        self._json({"error": "not found"}, 404)


def serve(rt, port=8765, host="127.0.0.1"):
    S["rt"] = rt
    threading.Thread(target=pump, args=(rt.bus,), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.token = _token()
    httpd.models = lambda: _models(rt)
    log("web on http://%s:%d/" % (host, port))
    print("web: http://%s:%d/?t=%s" % (host, port, httpd.token))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _models(rt):
    try:
        return provider.build(config.CFG).models()
    except Exception:
        return []