"""Android-only tools: launch and enumerate apps."""
from ..platform import current


def open_app(package):
    p = current()
    if not hasattr(p, "open_app"):
        return {"error": "not supported on this platform"}
    return ({"launched": True, "package": package} if p.open_app(package)
            else {"error": "could not launch %s" % package})


def list_apps(limit=120):
    p = current()
    if not hasattr(p, "list_apps"):
        return {"error": "not supported on this platform"}
    rows = p.list_apps(int(limit or 120))
    return {"apps": "\n".join(rows) if rows else "(none)"}