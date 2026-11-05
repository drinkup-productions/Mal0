"""Perception: screen capture, window enumeration, focus, notifications."""
import os
import time

from ..core import config, profiles
from ..platform import current


def screen_shot(monitor=0, scale=0.5):
    p = current()
    try:
        shots = p.screens()
    except Exception as exc:
        return {"error": "screens failed: %s" % exc}
    if not shots:
        return {"error": "no displays reported by this platform"}
    idx = int(monitor or 0)
    if not 0 <= idx < len(shots):
        return {"error": "monitor %d out of range 0-%d" % (idx, len(shots) - 1)}
    s = shots[idx]
    region = (s["left"], s["top"], s["left"] + s["width"], s["top"] + s["height"])
    try:
        img = p.grab(region)
    except Exception as exc:
        return {"error": "grab failed: %s" % exc}
    if img is None:
        return {"error": "capture unsupported here"}
    sc = max(0.1, min(1.0, float(scale or 0.5)))
    if sc < 1.0:
        img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))))
    out = os.path.join(config.paths().output, "screen_%s.png" % time.strftime("%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    return {"path": out, "width": img.width, "height": img.height, "monitor": idx,
            "note": "PNG saved. You cannot see pixels; use list_windows for text."}


def list_windows(limit=60, all_profiles=False):
    try:
        ws = current().windows(int(limit or 60))
    except Exception as exc:
        return {"error": str(exc)}
    if not ws:
        return {"windows": "(none)"}
    prof = profiles.active_name()
    if not all_profiles and profiles.windows(prof):
        keep = [w for w in ws if profiles.visible(prof, w["title"], w["proc"])]
        hidden = len(ws) - len(keep)
        if not keep:
            return {"windows": "(nothing matches profile %s)" % prof,
                    "hidden": hidden,
                    "note": "profile %s filters window titles; retry with all_profiles"
                            % prof}
        res = {"windows": "\n".join("%d| %s [%s]" % (w["hwnd"], w["title"], w["proc"])
                                    for w in keep), "profile": prof}
        if hidden:
            res["hidden"] = hidden
        return res
    return {"windows": "\n".join("%d| %s [%s]" % (w["hwnd"], w["title"], w["proc"])
                                 for w in ws)}


def focus_window(hwnd):
    try:
        ok = current().focus_window(int(hwnd))
    except Exception as exc:
        return {"error": str(exc)}
    return {"focused": bool(ok), "hwnd": int(hwnd)}


def notify(title, text):
    try:
        ok = current().notify(str(title or "MalO")[:80], str(text or "")[:300])
    except Exception as exc:
        return {"error": str(exc)}
    return {"notified": bool(ok)}