"""Broker test client and worker. Reads broker_token from config."""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

from ..core import config


def _base():
    return "http://127.0.0.1:%d" % int(config.get("broker_port") or 8766)


def _call(method, path, body=None, token="", timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_base() + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


def _claim(token):
    status, row = _call("GET", "/job?claim=1", token=token)
    return row if status == 200 else None


def _complete(jid, text, token, fail=False):
    tail = "fail" if fail else "result"
    key = "error" if fail else "result"
    _call("POST", "/job/%s/%s" % (jid, tail), {key: text}, token)


def _prep(args):
    config.load()
    token = args.token or config.get("broker_token") or ""
    if args.verbose:
        print("token len %d sha %s" % (
            len(token), hashlib.sha256(token.encode()).hexdigest()[:12]))
    if not token:
        raise SystemExit("no token - run: python -m malo.core.broker --pair")
    try:
        _call("GET", "/health", token=token)
    except Exception as exc:
        raise SystemExit("broker unreachable on %s (%s)" % (_base(), exc))
    try:
        _call("GET", "/whoami", token=token)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SystemExit("token rejected - re-pair and restart the broker")
        raise
    return token


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal")
    ap.add_argument("--tier", default="large", choices=("small", "large"))
    ap.add_argument("--conv", default="")
    ap.add_argument("--idem")
    ap.add_argument("--token", default="")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--work", action="store_true")
    ap.add_argument("--secs", type=float, default=3.0)
    ap.add_argument("--complete")
    ap.add_argument("--fail")
    args = ap.parse_args(argv)
    token = _prep(args)

    if args.complete or args.fail:
        jid = args.complete or args.fail
        _complete(jid, args.fail or "done", token, fail=bool(args.fail))
        print("completed", jid)
        return 0

    if args.work:
        n = 0
        while True:
            job = _claim(token)
            if not job:
                print("queue empty after %d" % n)
                return 0
            n += 1
            print("claimed %s: %s" % (job["id"], job["goal"][:60]))
            time.sleep(args.secs)
            _complete(job["id"], "result for %s" % job["id"], token)
            print("done %s" % job["id"])

    if not args.goal:
        ap.error("--goal is required")

    idem = args.idem or str(uuid.uuid4())
    status, body = _call("POST", "/job",
                         {"goal": args.goal, "tier": args.tier,
                          "idem": idem, "conv": args.conv}, token)
    if status != 201:
        raise SystemExit("enqueue failed: %s %s" % (status, body))
    jid = body["id"]
    print("queued", jid, "(duplicate)" if body.get("duplicate") else "")
    if not args.watch:
        return 0
    end = time.time() + args.timeout
    while time.time() < end:
        status, row = _call("GET", "/job/%s" % jid, token=token)
        if row and row.get("status") in ("done", "failed", "expired"):
            print(json.dumps(row, indent=2)[:8000])
            return 0 if row["status"] == "done" else 1
        time.sleep(2)
    print("timeout")
    return 1


if __name__ == "__main__":
    sys.exit(main())