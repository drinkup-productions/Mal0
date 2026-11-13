"""Memory block tools."""
from ..core import memctl


def memory_status():
    return memctl.status()


def memory_view(label="notes"):
    return {"label": label, "content": memctl.read(label)}


def memory_write(label, text):
    memctl.write(label, text)
    return {"label": label, "bytes": len(text or "")}


def memory_append(label, text):
    memctl.append(label, text)
    return {"label": label, "appended": (text or "")[:200]}


def memory_prune():
    return memctl.prune()