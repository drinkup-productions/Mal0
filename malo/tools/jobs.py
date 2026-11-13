"""Agent-facing broker tools."""
import json
import urllib.error
import urllib.request

from ..core import config

BASE = "http://127.0.0.1:%d"


def _url():
    return BASE % int(config.get("broker_port") or 8766)


def _call(method, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_url() + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    token = config.get("broker_token") or ""
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.reason}
    except Exception as exc:
        return 0, {"error": "%s: %s" % (type(exc).__name__, exc)}


def job_enqueue(goal, tier="large", conv="", idem=""):
    body = {"goal": goal, "tier": tier}
    if conv:
        body["conv"] = conv
    if idem:
        body["idem"] = idem
    status, data = _call("POST", "/job", body)
    if status != 201:
        return {"error": "enqueue failed: %s %s" % (status, data)}
    return data


def job_claim():
    status, data = _call("GET", "/job?claim=1")
    if status == 204 or not data:
        return {"job": None}
    return data


def job_status(job_id):
    status, data = _call("GET", "/job/%s" % job_id)
    return data or {"error": status}


def job_result(job_id, result):
    status, data = _call("POST", "/job/%s/result" % job_id, {"result": result})
    return {"ok": status == 204} if status != 204 else {"ok": True, "error": data}


def job_fail(job_id, error):
    status, _ = _call("POST", "/job/%s/fail" % job_id, {"error": error})
    return {"ok": status == 204}