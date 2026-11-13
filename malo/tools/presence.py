"""Overlay control tools."""
from ..core import idle

_OVERLAY = None


def bind(overlay):
    global _OVERLAY
    _OVERLAY = overlay


def _get():
    if _OVERLAY is None:
        return {"error": "no overlay"}
    return _OVERLAY


def presence_show():
    o = _get()
    if isinstance(o, dict):
        return o
    o.show()
    return {"shown": True}


def presence_hide():
    o = _get()
    if isinstance(o, dict):
        return o
    o.hide()
    return {"hidden": True}


def presence_say(text, ms=4000):
    o = _get()
    if isinstance(o, dict):
        return o
    if not idle.may_speak():
        return {"said": False, "why": "rate limited"}
    o.say(text, int(ms))
    idle.spoke()
    return {"said": True}


def presence_quiet(minutes=60):
    o = _get()
    if isinstance(o, dict):
        return o
    o.quiet(int(minutes))
    return {"quiet_minutes": int(minutes)}