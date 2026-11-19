import os

_IMPL = None


def current():
    global _IMPL
    if _IMPL is None:
        if os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_PRIVATE"):
            from .android import Android
            _IMPL = Android()
        else:
            from .posix import Posix
            _IMPL = Posix()
    return _IMPL