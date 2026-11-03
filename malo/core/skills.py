"""User-authored tools. A .py in skills/ with SPECS plus matching functions registers."""
import importlib.util
import os
import sys
import threading

from . import config
from .log import log

LOCK = threading.RLock()
SPECS = {}
FUNCS = {}
BAD = {}


def _dir():
    d = os.path.join(config.paths().root, "skills")
    os.makedirs(d, exist_ok=True)
    return d


def load_all():
    with LOCK:
        SPECS.clear()
        FUNCS.clear()
        BAD.clear()
        for name in sorted(os.listdir(_dir())):
            if not name.endswith(".py") or name.startswith("_"):
                continue
            mod = name[:-3]
            path = os.path.join(_dir(), name)
            try:
                spec = importlib.util.spec_from_file_location("malo_skill_" + mod, path)
                m = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = m
                spec.loader.exec_module(m)
                for s in (getattr(m, "SPECS", None) or []):
                    fn = getattr(m, s["function"]["name"], None)
                    if callable(fn):
                        SPECS[s["function"]["name"]] = s
                        FUNCS[s["function"]["name"]] = fn
            except Exception as exc:
                BAD[mod] = str(exc)
                log("skill %s failed: %s" % (mod, exc))
    return SPECS


def specs():
    return list(SPECS.values())


def call(name, args):
    fn = FUNCS.get(name)
    if not fn:
        return {"error": "unknown skill " + name}
    return fn(**(args or {}))


def write(name, code):
    name = "".join(c for c in str(name) if c.isalnum() or c == "_")
    if not name:
        return {"error": "bad skill name"}
    p = os.path.join(_dir(), name + ".py")
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(code or "")
    load_all()
    if name in BAD:
        return {"error": BAD[name], "path": p}
    return {"saved": p, "tools": sorted(SPECS)}


def listing():
    load_all()
    rows = ["%s - %s" % (n, s["function"]["description"][:70]) for n, s in SPECS.items()]
    rows += ["%s FAILED: %s" % (n, e) for n, e in BAD.items()]
    return {"skills": "\n".join(rows) or "(none)"}