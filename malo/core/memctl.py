"""Memory blocks on disk. Files under the local backend MemFS, git as undo."""
import json
import os
import subprocess
import shutil
from . import config
from .log import log

LABELS = ("persona", "human", "notes", "MEMORY")


def root():
    base = os.environ.get("LETTA_LOCAL_BACKEND_DIR") or \
        os.path.join(os.path.expanduser("~"), ".letta", "lc-local-backend")
    agent = config.get("letta_agent") or ""
    if not agent:
        return ""
    return os.path.join(base, "memfs", agent, "memory")


def _path(label):
    label = (label or "").strip().replace(".md", "")
    if label not in LABELS:
        raise ValueError("unknown block: %s (have %s)" % (label, ", ".join(LABELS)))
    return os.path.join(root(), label + ".md")


def _exe(name):
    found = shutil.which(name)
    if not found:
        return []
    return ["cmd", "/c", found] if found.lower().endswith((".cmd", ".bat")) else [found]


def _git(*args):
    d = root()
    base = _exe("git")
    if not d or not os.path.isdir(d) or not base:
        return ""
    try:
        out = subprocess.run(base + ["-C", d] + list(args), capture_output=True,
                             text=True, timeout=30)
        return (out.stdout or "").strip()
    except Exception as exc:
        log("memctl git: %s" % exc)
        return ""


def tokens():
    d = root()
    if not d:
        return {"error": "no agent set"}
    if not os.path.isdir(d):
        return {"total_tokens": 0, "files": [], "note": "no memory dir yet"}
    base = _exe("letta")
    if not base:
        return {"error": "letta not on PATH"}
    try:
        out = subprocess.run(base + ["memory", "tokens", "--memory-dir", d,
                                     "--format", "json"],
                             capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout or "{}")
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def total():
    t = tokens()
    return int(t.get("total_tokens") or 0)


def read(label):
    p = _path(label)
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def write(label, text, msg="memory write"):
    p = _path(label)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text or "")
    commit(msg)
    return p


def append(label, text, msg="memory append"):
    body = read(label)
    line = (text or "").strip()
    if not line:
        return ""
    sep = "" if not body or body.endswith("\n") else "\n"
    return write(label, body + sep + line + "\n", msg)


def status():
    t = tokens()
    budget = int(config.get("memory_budget_tokens") or 800)
    if "error" in t:
        return t
    t["budget"] = budget
    t["over"] = int(t.get("total_tokens") or 0) > budget
    t["dir"] = root()
    return t


def prune(budget=None):
    """Trim notes.md oldest-first until under budget. Logs what it dropped."""
    budget = int(budget or config.get("memory_budget_tokens") or 800)
    now = total()
    if now <= budget:
        return {"pruned": 0, "tokens": now, "budget": budget}
    body = read("notes")
    lines = [l for l in body.splitlines() if l.strip()]
    dropped = []
    while lines and total() > budget:
        dropped.append(lines.pop(0))
        write("notes", "\n".join(lines) + ("\n" if lines else ""),
              "memory prune %d" % len(dropped))
    if dropped:
        logpath = os.path.join(config.paths().root, "memory_dropped.log")
        with open(logpath, "a", encoding="utf-8") as fh:
            for d in dropped:
                fh.write("%s\n" % d)
        commit("memory prune: dropped %d" % len(dropped))
    return {"pruned": len(dropped), "tokens": total(), "budget": budget,
            "dropped": dropped[:20], "log": "memory_dropped.log"}