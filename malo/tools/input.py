"""Mouse and keyboard. Moves the real cursor."""
from ..platform import current


def _p():
    p = current()
    return p if hasattr(p, "mouse_move") else None


def mouse_move(x, y):
    p = _p()
    if not p:
        return {"error": "input unsupported here"}
    return {"moved": p.mouse_move(x, y), "x": int(x), "y": int(y)}


def click(x=None, y=None, button="left", double=False):
    p = _p()
    if not p:
        return {"error": "input unsupported here"}
    return {"clicked": p.mouse_click(x, y, button, bool(double)), "at": [x, y]}


def scroll(amount=3):
    p = _p()
    if not p:
        return {"error": "input unsupported here"}
    return {"scrolled": p.mouse_scroll(amount)}


def key(keys):
    p = _p()
    if not p:
        return {"error": "input unsupported here"}
    return {"sent": bool(p.key_press(keys)), "keys": keys}


def type_text(text):
    p = _p()
    if not p:
        return {"error": "input unsupported here"}
    return {"typed": bool(p.type_text(text)), "chars": len(str(text))}