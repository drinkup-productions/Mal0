"""Append-only log. Path is injected once at startup."""
import time

_PATH = None

def set_path(path):
    global _PATH
    _PATH = path

def log(msg):
    if not _PATH:
        return
    try:
        with open(_PATH, "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass