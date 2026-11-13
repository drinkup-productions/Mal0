"""Job broker. A local queue between a thin controller and this machine.

    python -m malo.core.broker --pair          mint a device token
    python -m malo.core.broker --serve         run the HTTP broker
"""
import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .log import log

RESULT_CAP = 24000
MAX_ATTEMPTS = 3
TTL = 86400
ROW_CAP = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY,
  idem TEXT UNIQUE,
  goal TEXT NOT NULL,
  tier TEXT NOT NULL CHECK(tier IN ('small','large')),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK(status IN ('queued','claimed','done','failed','expired')),
  result TEXT, error TEXT, conv TEXT,
  created REAL NOT NULL, claimed REAL, done REAL,
  attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS devices(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  issued REAL NOT NULL,
  last_seen REAL,
  revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created);
"""

_LOCK = threading.Lock()


def db_path():
    return os.path.join(config.paths().root, "broker.db")


def connect():
    conn = sqlite3.connect(db_path(), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def pair(name="cli"):
    config.load()
    token = secrets.token_urlsafe(32)
    conn = connect()
    try:
        did = "dev-" + secrets.token_hex(6)
        conn.execute("INSERT INTO devices(id, name, token_hash, issued) VALUES (?,?,?,?)",
                     (did, name, _hash(token), time.time()))
    finally:
        conn.close()
    config.CFG["broker_token"] = token
    config.save()
    print("device: %s" % did)
    print("token : %s" % token)
    return token


def _auth(conn, token):
    if not token:
        return None
    row = conn.execute("SELECT * FROM devices WHERE token_hash=? AND revoked=0",
                       (_hash(token),)).fetchone()
    if row:
        conn.execute("UPDATE devices SET last_seen=? WHERE id=?", (time.time(), row["id"]))
    return row


def _sweep(conn):
    now = time.time()
    conn.execute("UPDATE jobs SET status='expired' WHERE status IN ('queued','claimed') "
                 "AND created < ?", (now - TTL,))
    n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','claimed')"
                     ).fetchone()[0]
    if n > ROW_CAP:
        conn.execute("UPDATE jobs SET status='expired' WHERE id IN ("
                     "SELECT id FROM jobs WHERE status IN ('queued','claimed') "
                     "ORDER BY created LIMIT ?)", (n - ROW_CAP,))


def requeue_stale(conn):
    """Claimed work belongs to a dead worker after a restart."""
    now = time.time()
    cur = conn.execute("UPDATE jobs SET status='queued', claimed=NULL "
                       "WHERE status='claimed' AND attempts < ?", (MAX_ATTEMPTS,))
    gave_up = conn.execute("UPDATE jobs SET status='failed', done=?, "
                           "error='gave up after retries' "
                           "WHERE status='claimed' AND attempts >= ?",
                           (now, MAX_ATTEMPTS)).rowcount
    if cur.rowcount or gave_up:
        log("requeued %d stale job(s), failed %d" % (cur.rowcount, gave_up))
        print("requeued %d stale job(s), failed %d" % (cur.rowcount, gave_up))


def enqueue(conn, goal, tier, idem, conv):
    with _LOCK:
        _sweep(conn)
        if idem:
            row = conn.execute("SELECT id FROM jobs WHERE idem=?", (idem,)).fetchone()
            if row:
                return row["id"], False
        jid = "job-" + secrets.token_hex(8)
        conn.execute("INSERT INTO jobs(id, idem, goal, tier, conv, created) "
                     "VALUES (?,?,?,?,?,?)", (jid, idem, goal, tier, conv, time.time()))
        return jid, True


def claim(conn):
    with _LOCK:
        _sweep(conn)
        row = conn.execute("SELECT * FROM jobs WHERE status='queued' AND attempts<? "
                           "ORDER BY created LIMIT 1", (MAX_ATTEMPTS,)).fetchone()
        if not row:
            return None
        cur = conn.execute("UPDATE jobs SET status='claimed', claimed=?, attempts=attempts+1 "
                           "WHERE id=? AND status='queued'", (time.time(), row["id"]))
        if cur.rowcount != 1:
            return None
        return dict(conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())


def finish(conn, jid, result=None, error=None):
    text = (error or result or "")[:RESULT_CAP]
    conn.execute("UPDATE jobs SET status=?, result=?, error=?, done=? WHERE id=?",
                 ("failed" if error else "done",
                  None if error else text, error, time.time(), jid))
    return conn.execute("SELECT COUNT(*) FROM jobs WHERE id=?", (jid,)).fetchone()[0] == 1


class Handler(BaseHTTPRequestHandler):
    server_version = "MalOBroker/1"

    def log_message(self, fmt, *a):
        log("broker %s" % (fmt % a))

    def _send(self, code, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def _token(self):
        head = self.headers.get("Authorization") or ""
        return head[7:].strip() if head.lower().startswith("bearer ") else ""

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _guard(self, conn):
        token = self._token()
        if not token:
            log("broker 401: no Authorization header")
            self._send(401, {"error": "no token"})
            return False
        row = _auth(conn, token)
        if not row:
            got = _hash(token)[:12]
            have = [r["token_hash"][:12] for r in
                    conn.execute("SELECT token_hash FROM devices WHERE revoked=0")]
            log("broker 401: got %s have %s" % (got, have))
            self._send(401, {"error": "bad token"})
            return False
        return True

    def do_GET(self):
        conn = connect()
        try:
            parts = urllib.parse.urlparse(self.path)
            path = parts.path.rstrip("/")
            if path == "/health":
                return self._send(200, {"ok": True})
            if not self._guard(conn):
                return
            if path == "/whoami":
                return self._send(200, {"device": _auth(conn, self._token())["id"]})
            if path == "/job":
                if urllib.parse.parse_qs(parts.query).get("claim"):
                    job = claim(conn)
                    return self._send(200, job) if job else self._send(204)
                rows = conn.execute(
                    "SELECT id, goal, tier, status, created, attempts FROM jobs "
                    "WHERE status IN ('queued','claimed') ORDER BY created LIMIT 50"
                ).fetchall()
                return self._send(200, {"jobs": [dict(r) for r in rows]})
            if path.startswith("/job/"):
                row = conn.execute("SELECT * FROM jobs WHERE id=?",
                                   (path[5:],)).fetchone()
                return self._send(200, dict(row)) if row else self._send(404, {"error": "no job"})
            return self._send(404, {"error": "no route"})
        finally:
            conn.close()

    def do_POST(self):
        conn = connect()
        try:
            if not self._guard(conn):
                return
            path = urllib.parse.urlparse(self.path).path.rstrip("/")
            body = self._body()
            if path == "/job":
                goal = (body.get("goal") or "").strip()
                tier = body.get("tier") or "large"
                if not goal:
                    return self._send(400, {"error": "goal required"})
                if tier not in ("small", "large"):
                    return self._send(400, {"error": "bad tier"})
                jid, fresh = enqueue(conn, goal, tier, body.get("idem"),
                                     body.get("conv") or "")
                return self._send(201, {"id": jid, "duplicate": not fresh})
            if path.startswith("/job/") and path.endswith("/result"):
                jid = path[5:-7]
                if not finish(conn, jid, result=body.get("result")):
                    return self._send(404, {"error": "no job"})
                return self._send(204)
            if path.startswith("/job/") and path.endswith("/fail"):
                jid = path[5:-5]
                if not finish(conn, jid, error=body.get("error") or "failed"):
                    return self._send(404, {"error": "no job"})
                return self._send(204)
            return self._send(404, {"error": "no route"})
        finally:
            conn.close()


def serve(host=None, port=None):
    host = host or config.get("broker_host") or "127.0.0.1"
    port = int(port or config.get("broker_port") or 8766)
    conn = connect()
    try:
        requeue_stale(conn)
        _sweep(conn)
    finally:
        conn.close()
    srv = ThreadingHTTPServer((host, port), Handler)
    log("broker on http://%s:%d" % (host, port))
    print("broker on http://%s:%d" % (host, port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", nargs="?", const="cli")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    args = ap.parse_args(argv)
    if args.pair:
        pair(args.pair)
        return 0
    if args.serve:
        serve(args.host, args.port)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())