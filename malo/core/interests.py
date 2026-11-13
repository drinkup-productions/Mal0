"""Topic rotation for idle research."""
import time

from . import config

RECENT = 7 * 86400


def _recent():
    return dict(config.get("interest_recent") or {})


def seed():
    rows = config.get("interests") or []
    if rows:
        return list(rows)
    base = ["blacksmithing", "forging techniques", "heat treatment of steel",
            "workshop tooling", "pattern welding"]
    config.CFG["interests"] = base
    config.save()
    return base


def pick():
    """Oldest topic not used inside the window, or None."""
    now = time.time()
    recent = _recent()
    rows = [t for t in seed() if now - float(recent.get(t, 0)) >= RECENT]
    if not rows:
        return None
    rows.sort(key=lambda t: float(recent.get(t, 0)))
    return rows[0]


def mark(topic):
    recent = _recent()
    recent[topic] = time.time()
    cutoff = time.time() - RECENT
    config.CFG["interest_recent"] = {k: v for k, v in recent.items()
                                     if float(v) >= cutoff}
    config.save()