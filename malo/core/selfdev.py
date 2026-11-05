"""Self-development: proposals, patch application, test gating."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

from . import config
from .log import log

SKIP = {".git", "__pycache__", "bin", ".venv", ".buildozer", "build", "dist"}
DEFAULT_TEST_CMD = "python -m unittest discover -s tests -t . -q"


def _root():
    r = config.get("repo")
    if not r or not os.path.isdir(r):
        raise ValueError("repo not set or missing")
    return os.path.abspath(r)


def _pid(pid):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(pid or ""))


def _prop_dir(pid=None):
    d = os.path.join(config.paths().root, "proposals")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, _pid(pid)) if pid else d


def _sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def grep(pattern, glob="*.py", limit=80):
    import re as _re
    root = _root()
    rx = _re.compile(pattern)
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in files:
            if not f.endswith(glob.lstrip("*")):
                continue
            p = os.path.join(base, f)
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for i, ln in enumerate(fh, 1):
                        if rx.search(ln):
                            out.append("%s:%d: %s" % (os.path.relpath(p, root), i,
                                                      ln.rstrip()[:200]))
                            if len(out) >= limit:
                                return {"matches": "\n".join(out), "truncated": True}
            except Exception:
                pass
    return {"matches": "\n".join(out) or "(no matches)"}


def run_tests(timeout=300):
    root = _root()
    cmd = config.get("self_test_cmd") or DEFAULT_TEST_CMD
    try:
        r = subprocess.run(cmd, cwd=root, shell=True, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "tests timed out after %ss" % timeout}
    except Exception as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    tail = (r.stdout + r.stderr)[-3000:]
    return {"ok": r.returncode == 0, "code": r.returncode, "output": tail or "(silent)"}


def propose(title, rationale, files):
    """files: {"malo/core/x.py": "full new content"}"""
    if not isinstance(files, dict) or not files:
        return {"error": "no files given"}
    root = _root()
    plan = []
    for rel, content in files.items():
        rel = str(rel).replace("\\", "/").lstrip("/")
        target = os.path.abspath(os.path.join(root, rel))
        if target != root and not target.startswith(root + os.sep):
            return {"error": "outside the repo: %s" % rel}
        plan.append((rel, target, content))
    pid = "%d" % int(time.time() * 1000)
    d = _prop_dir(pid)
    os.makedirs(d, exist_ok=True)
    meta = {"id": pid, "title": title, "rationale": rationale, "at": time.time(),
            "files": [], "sha": {}}
    for rel, target, content in plan:
        copy = os.path.join(d, rel.replace("/", "__"))
        with open(copy, "w", encoding="utf-8", newline="") as fh:
            fh.write(content or "")
        meta["files"].append(rel)
        meta["sha"][rel] = _sha(target) if os.path.isfile(target) else ""
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    log("proposal %s: %s" % (pid, title))
    return {"proposal": pid, "files": meta["files"],
            "next": "apply(id) to install, or leave it for review"}


def proposals(limit=20):
    d = _prop_dir()
    names = [n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))]
    rows = []
    for name in sorted(names, key=lambda n: n, reverse=True)[:limit]:
        m = os.path.join(d, name, "meta.json")
        if os.path.isfile(m):
            try:
                with open(m, encoding="utf-8") as fh:
                    rows.append(json.load(fh))
            except Exception:
                pass
    if not rows:
        return {"proposals": "(none)"}
    return {"proposals": "\n".join(
        "%s| %s (%s)%s - %s" % (r["id"], r["title"], ", ".join(r["files"]),
                                " [applied]" if r.get("applied_at") else "",
                                (r.get("rationale") or "")[:80])
        for r in rows)}


def discard(pid):
    d = _prop_dir(pid)
    if not os.path.isdir(d):
        return {"error": "no proposal %s" % pid}
    shutil.rmtree(d, ignore_errors=True)
    return {"discarded": _pid(pid)}


def _restore(backups):
    for target, snap, existed in backups:
        if snap and os.path.isfile(snap):
            try:
                shutil.copy2(snap, target)
            except Exception as exc:
                log("revert failed for %s: %s" % (target, exc))
        elif not existed:
            try:
                os.remove(target)
            except Exception:
                pass


def apply(pid, force=False):
    from ..tools import core as tools
    d = _prop_dir(pid)
    meta_p = os.path.join(d, "meta.json")
    if not os.path.isfile(meta_p):
        return {"error": "no proposal %s" % pid}
    with open(meta_p, encoding="utf-8") as fh:
        meta = json.load(fh)
    if meta.get("applied_at") and not force:
        return {"error": "already applied %s - pass force to reapply"
                % time.strftime("%Y-%m-%d %H:%M", time.localtime(meta["applied_at"]))}
    root = _root()

    plan = []
    for rel in meta["files"]:
        target = os.path.join(root, rel)
        copy = os.path.join(d, rel.replace("/", "__"))
        if not os.path.isfile(copy):
            return {"error": "proposal file missing: %s" % rel}
        want = (meta.get("sha") or {}).get(rel)
        if want and not force:
            if not os.path.isfile(target):
                return {"error": "target vanished since the proposal: %s" % rel}
            if _sha(target) != want:
                return {"error": "%s changed since the proposal - re-propose or force"
                        % rel}
        plan.append((target, copy))

    backups = []
    try:
        for target, copy in plan:
            existed = os.path.isfile(target)
            backups.append((target, tools._snapshot(target), existed))
            shutil.copy2(copy, target)
        res = run_tests()
    except Exception as exc:
        _restore(backups)
        return {"applied": False, "reverted": True,
                "error": "%s: %s" % (type(exc).__name__, exc)}
    if not res.get("ok"):
        _restore(backups)
        return {"applied": False, "reverted": True, "tests": res}
    meta["applied_at"] = time.time()
    with open(meta_p, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return {"applied": True, "files": meta["files"], "tests": res,
            "note": "restart to load the change"}