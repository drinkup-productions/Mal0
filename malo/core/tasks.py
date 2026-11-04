"""One active task at a time. The newest user instruction supersedes the rest."""
import threading
import time

_LOCK = threading.RLock()
_S = {"text": "", "at": 0.0}


def begin(text):
    with _LOCK:
        _S["text"] = " ".join(str(text or "").split())[:400]
        _S["at"] = time.time()
    return _S["text"]


def current():
    with _LOCK:
        return dict(_S)


def age():
    with _LOCK:
        return max(0.0, time.time() - (_S["at"] or time.time()))


def clear():
    with _LOCK:
        _S["text"] = ""
        _S["at"] = 0.0


def _age(secs):
    if secs < 3600:
        return "%dm" % max(1, int(secs // 60))
    if secs < 86400:
        return "%dh" % int(secs // 3600)
    return "%dd" % int(secs // 86400)