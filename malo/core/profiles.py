"""Workspace profiles: named root sets, window filters and a standing brief."""
import os
import re

from . import config

BUILTIN = "default"
MAX_ROOTS = 12
MAX_WINDOWS = 40
MAX_NAME = 32
MAX_BRIEF = 1200


def _expand(p):
    p = os.path.expandvars(os.path.expanduser(str(p or "").strip()))
    if not p:
        return ""
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def slug(name):
    s = re.sub(r"[^a-z0-9_-]+", "-", str(name or "").strip().lower()).strip("-")
    return s[:MAX_NAME]


def _table():
    t = config.get("profiles")
    return t if isinstance(t, dict) else {}


def names():
    return [BUILTIN] + sorted(n for n in _table() if n != BUILTIN)


def get(name=None):
    n = slug(name) if name else active_name()
    if n == BUILTIN or n not in _table():
        return {"name": n,
                "roots": [_expand(config.paths().workspace_default)],
                "windows": [], "brief": ""}
    row = _table().get(n) or {}
    return {"name": n,
            "roots": [r for r in (row.get("roots") or []) if r],
            "windows": [w for w in (row.get("windows") or []) if w],
            "brief": row.get("brief") or ""}


def active_name():
    n = slug(config.get("active_profile") or "")
    return n if n in names() else BUILTIN


def roots(name=None):
    return get(name)["roots"]


def windows(name=None):
    return get(name)["windows"]


def brief(name=None):
    return get(name)["brief"]


def rows():
    act = active_name()
    out = []
    for n in names():
        p = get(n)
        out.append({"name": n, "active": n == act,
                    "roots": len(p["roots"]), "windows": len(p["windows"]),
                    "brief": bool(p["brief"])})
    return out


def visible(profile, title, proc=""):
    """True if a window passes the filter. An empty filter shows everything."""
    pats = windows(profile)
    if not pats:
        return True
    hay = ("%s %s" % (title or "", proc or "")).lower()
    return any(p in hay for p in pats)


def save(name, roots=None, windows=None, brief=None):
    n = slug(name)
    if not n:
        return {"error": "empty profile name"}
    t = dict(_table())
    row = dict(t.get(n) or {})
    if roots is not None:
        row["roots"] = [r for r in (_expand(x) for x in roots) if r][:MAX_ROOTS]
    if windows is not None:
        row["windows"] = [str(w).strip().lower() for w in windows
                          if str(w).strip()][:MAX_WINDOWS]
    if brief is not None:
        row["brief"] = str(brief).strip()[:MAX_BRIEF]
    t[n] = row
    config.CFG["profiles"] = t
    config.save()
    return {"saved": n, "roots": row.get("roots") or [],
            "windows": row.get("windows") or []}


def use(name):
    n = slug(name)
    if n not in names():
        return {"error": "no such profile: %s" % n}
    p = get(n)
    ws = p["roots"][0] if p["roots"] else config.paths().workspace_default
    config.CFG["active_profile"] = n
    config.CFG["workspace"] = ws
    config.CFG["allow_roots"] = list(p["roots"][1:])
    config.CFG["wake_brief"] = p["brief"]
    config.save()
    return {"profile": n, "workspace": ws, "extra_roots": config.CFG["allow_roots"],
            "windows": p["windows"], "brief": p["brief"]}


def remove(name):
    n = slug(name)
    if n == BUILTIN:
        return {"error": "the default profile cannot be removed"}
    t = dict(_table())
    if n not in t:
        return {"error": "no such profile: %s" % n}
    t.pop(n)
    config.CFG["profiles"] = t
    config.save()
    if active_name() == n:
        use(BUILTIN)
    return {"removed": n}