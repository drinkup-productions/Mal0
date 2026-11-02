"""Headpat / wrong signal log."""
import json
import time

from .config import paths
from .log import log


def add(polarity, text="", prompt="", reply="", persona=""):
    row = {"ts": int(time.time()), "persona": persona, "polarity": polarity,
           "text": (text or "").strip()[:400],
           "prompt": (prompt or "")[:300], "reply": (reply or "")[:300]}
    try:
        with open(paths().feedback, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        log("feedback write failed: %s" % exc)
    return row


def _rows():
    out = []
    try:
        with open(paths().feedback, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return out


def recent(n=4):
    return _rows()[-n:]


def counts():
    good = bad = 0
    for r in _rows():
        if r.get("polarity") == "good":
            good += 1
        elif r.get("polarity") == "bad":
            bad += 1
    return {"good": good, "bad": bad}