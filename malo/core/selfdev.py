"""Self-development: proposals, patch application, test gating."""
import json
import os
import shutil
import subprocess
import time

from . import config
from .log import log

SKIP = {".git", "__pycache__", "bin", ".venv", ".buildozer", "build", "dist"}


def _root():
    r = config.get("repo")
    if not r or not os.path.isdir(r):
        raise ValueError("repo not set or missing")
    return os.path.abspath(r)


def _prop_dir(pid=None):
    d = os.path.join(config.paths().root, "proposals")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, str(pid)) if pid else d


def grep(pattern, glob="*.py", limit=80):
    import re
    root = _root()
    rx = re.compile(pattern)
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
                            out.append("%s:%d: %s" % (os.path.relpath(p, root), i, ln.rstrip()[:200]))
                            if len(out) >= limit:
                                return {"matches": "\n".join(out), "truncated": True}
            except Exception:
                pass
    return {"matches": "\n".join(out) or "(no matches)"}


def run_tests(timeout=300):
    root = _root()
    cmd = config.get("self_test_cmd") or "python -m compileall -q malo"
    try:
        r = subprocess.run(cmd, cwd=root, shell=True, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "tests timed out"}
    tail = (r.stdout + r.stderr)[-3000:]
    return {"ok": r.returncode == 0, "code": r.returncode, "output": tail or "(silent)"}


def propose(title, rationale, files):
    """files: {"malo/core/x.py": "full new content"}"""
    if not isinstance(files, dict) or not files:
        return {"error": "no files given"}
    root = _root()
    pid = "%d" % int(time.time())
    d = _prop_dir(pid)
    os.makedirs(d, exist_ok=True)
    meta = {"id": pid, "title": title, "rationale": rationale, "at": time.time(), "files": []}
    for rel, content in files.items():
        rel = rel.replace("\\", "/").lstrip("/")
        target = os.path.join(root, rel)
        if not os.path.isfile(target):
            return {"error": "no such file in repo: %s" % rel}
        copy = os.path.join(d, rel.replace("/", "__"))
        with open(copy, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        meta["files"].append(rel)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    log("proposal %s: %s" % (pid, title))
    return {"proposal": pid, "files": meta["files"],
            "next": "apply(id) to install, or leave it for review"}


def proposals(limit=20):
    d = _prop_dir()
    rows = []
    for name in sorted(os.listdir(d), reverse=True)[:limit]:
        m = os.path.join(d, name, "meta.json")
        if os.path.isfile(m):
            try:
                with open(m, encoding="utf-8") as fh:
                    rows.append(json.load(fh))
            except Exception:
                pass
    if not rows:
        return {"proposals": "(none)"}
    return {"proposals": "\n".join("%s| %s (%s) - %s" % (r["id"], r["title"],
                                                         ", ".join(r["files"]), r["rationale"][:80])
                                   for r in rows)}


def apply(pid):
    from ..tools import core as tools
    d = _prop_dir(pid)
    meta_p = os.path.join(d, "meta.json")
    if not os.path.isfile(meta_p):
        return {"error": "no proposal %s" % pid}
    with open(meta_p, encoding="utf-8") as fh:
        meta = json.load(fh)
    root = _root()
    backups = []
    for rel in meta["files"]:
        target = os.path.join(root, rel)
        copy = os.path.join(d, rel.replace("/", "__"))
        if not os.path.isfile(copy):
            return {"error": "proposal file missing: %s" % rel}
        backups.append((target, tools._snapshot(target)))
        shutil.copy2(copy, target)
    res = run_tests()
    if not res["ok"]:
        for target, snap in backups:
            if snap and os.path.isfile(snap):
                shutil.copy2(snap, target)
        return {"applied": False, "reverted": True, "tests": res}
    return {"applied": True, "files": meta["files"], "tests": res,
            "note": "restart to load the change"}