import os
import sys

_IMPL = None


def current():
    global _IMPL
    if _IMPL is None:
        if os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_PRIVATE"):
            from .android import Android
            _IMPL = Android()
        elif sys.platform.startswith("win"):
            from .windows import Windows
            _IMPL = Windows()
        else:
            from .posix import Posix
            _IMPL = Posix()
    return _IMPL