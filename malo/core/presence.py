"""Persistent internal state: mood that decays, and a journal for continuity."""
import json
import os
import random
import threading
import time

from . import config

DEFAULTS = {"energy": 0.6, "warmth": 0.5, "focus": 0.5, "restless": 0.35, "last": 0.0}
DIM = ("energy", "warmth", "focus", "restless")
_LOCK = threading.RLock()


def _path():
    return os.path.join(config.paths().root, "presence.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        d = {}
    for k, v in DEFAULTS.items():
        d.setdefault(k, v)
    d.setdefault("journal", [])
    return d


def _save(d):
    try:
        with open(_path(), "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    except Exception:
        pass


def _decay(d):
    hours = max(0.0, (time.time() - (d.get("last") or time.time())) / 3600.0)
    for k in DIM:
        d[k] += (DEFAULTS[k] - d[k]) * min(1.0, hours / 6.0)
    return d


def nudge(**delta):
    with _LOCK:
        d = _decay(load())
        for k, v in delta.items():
            if k in DIM:
                d[k] = max(0.0, min(1.0, d[k] + v))
        d["last"] = time.time()
        _save(d)
        return d


def fragment():
    d = load()
    bits = []
    if d["energy"] < 0.3:
        bits.append("tired, short")
    elif d["energy"] > 0.75:
        bits.append("alert, animated")
    if d["warmth"] > 0.7:
        bits.append("openly fond")
    elif d["warmth"] < 0.3:
        bits.append("a little distant")
    if d["focus"] > 0.7:
        bits.append("locked on one thing")
    elif d["focus"] < 0.3:
        bits.append("scattered")
    if d["restless"] > 0.7:
        bits.append("restless, wants something to do")
    return ", ".join(bits) or "settled"


def appetite():
    d = load()
    since = (time.time() - (d.get("last") or time.time())) / 3600.0
    p = 0.2 + d["restless"] * 0.5 + d["warmth"] * 0.3 + min(1.0, since / 8) * 0.45
    return max(0.0, min(1.0, p))


def roll():
    return random.random() < appetite()


def journal_add(text, cap=12):
    with _LOCK:
        d = load()
        j = d.get("journal") or []
        j.append({"at": time.time(), "text": " ".join(str(text).split())[:300]})
        d["journal"] = j[-max(1, cap):]
        d["last"] = time.time()
        _save(d)


def journal_read(n=6):
    j = (load().get("journal") or [])[-max(1, n):]
    if not j:
        return ""
    now = time.time()
    return "\n".join("- (%s) %s" % (
        "%dm" % max(1, int((now - e["at"]) / 60)) if now - e["at"] < 86400
        else "%dd" % int((now - e["at"]) / 86400), e["text"]) for e in j)