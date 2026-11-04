"""UI Automation: address controls by name and role instead of pixel coordinates."""
import threading

_CACHE = {}
_LAST = {"key": 0}
_LOCK = threading.RLock()
MAX_ELEMENTS = 400


def _auto():
    import uiautomation as auto
    return auto


def _root(hwnd=None):
    auto = _auto()
    if hwnd:
        c = auto.ControlFromHandle(int(hwnd))
        if not c:
            raise LookupError("no window for hwnd %s" % hwnd)
        return c
    return auto.GetForegroundControl()


def _collect(ctrl, depth, limit):
    rows = []
    cache = {}

    def walk(node, d):
        if len(rows) >= limit or d > depth:
            return
        try:
            kids = node.GetChildren()
        except Exception:
            return
        for child in kids:
            if len(rows) >= limit:
                return
            try:
                i = len(rows)
                cache[i] = child
                r = child.BoundingRectangle
                rows.append("%d| %s %r id=%r class=%r [%d,%d,%d,%d]" % (
                    i, child.ControlTypeName, child.Name or "",
                    child.AutomationId or "", child.ClassName or "",
                    r.left, r.top, r.right, r.bottom))
            except Exception:
                continue
            walk(child, d + 1)

    walk(ctrl, 1)
    return rows, cache


def tree(hwnd=None, depth=3, limit=200):
    try:
        root = _root(hwnd)
    except Exception as exc:
        return {"error": "uia unavailable: %s" % exc}
    if not root:
        return {"error": "no window"}
    rows, cache = _collect(root, max(1, min(8, int(depth or 3))),
                           max(1, min(MAX_ELEMENTS, int(limit or 200))))
    key = int(hwnd) if hwnd else 0
    with _LOCK:
        _CACHE[key] = cache
        _LAST["key"] = key
    try:
        title = root.Name
    except Exception:
        title = ""
    return {"window": title, "count": len(rows),
            "elements": "\n".join(rows) or "(no children)"}


def find(name=None, hwnd=None, depth=6, limit=1):
    try:
        root = _root(hwnd)
    except Exception as exc:
        return {"error": "uia unavailable: %s" % exc}
    if not root:
        return {"error": "no window"}
    needle = str(name or "").lower()
    if not needle:
        return {"error": "name required"}
    rows, cache = _collect(root, max(1, min(10, int(depth or 6))), MAX_ELEMENTS)
    hits = []
    for i, line in enumerate(rows):
        if needle in line.lower():
            hits.append(i)
            if len(hits) >= max(1, int(limit or 1)):
                break
    if not hits:
        return {"found": False, "searched": len(rows)}
    key = int(hwnd) if hwnd else 0
    with _LOCK:
        _CACHE[key] = cache
        _LAST["key"] = key
    return {"found": True, "window": title, "matches": "\n".join(rows[i] for i in hits),
            "index": hits[0]}


def act(index=0, action="click", value=""):
    with _LOCK:
        cache = _CACHE.get(_LAST["key"]) or {}
        el = cache.get(int(index))
    if el is None:
        return {"error": "no element %s - call uia_tree or uia_find first" % index}
    a = str(action or "click").lower()
    try:
        if a == "click":
            try:
                el.GetInvokePattern().Invoke()
            except Exception:
                el.Click(simulateMove=False)
        elif a == "value":
            el.GetValuePattern().SetValue(str(value))
        elif a == "focus":
            el.SetFocus()
        elif a == "keys":
            el.SetFocus()
            el.SendKeys(str(value))
        elif a == "read":
            return {"text": el.Name or ""}
        else:
            return {"error": "unknown action " + a}
        label = el.Name or el.ControlTypeName
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    return {"ok": True, "action": a, "element": label}