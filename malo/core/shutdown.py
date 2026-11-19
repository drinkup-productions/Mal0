"""Graceful shutdown: one last turn to write notes, then a raw fallback.

Three layers. Layer 1 asks the agent for a summary. Layer 2 writes the
transcript tail if layer 1 fails, times out or is bypassed. Layer 3 hooks
the console and SIGTERM so a window close lands in layer 1 too.
"""
import atexit
import ctypes
import hashlib
import json
import os
import signal
import threading
import time
from datetime import datetime, timezone

from . import config, memctl
from .log import log

TIMEOUT = 90.0
FALLBACK_TURNS = 24
FLAG = "quit.flag"

_app = None
_lock = threading.Lock()
_state = {"armed": False, "running": False, "done": False}
_keepalive = []

PROMPT = """\
SYSTEM: SHUTDOWN SEQUENCE

The application is closing. This is your only chance to persist context.

1. Re-read the conversation above.
2. Rewrite memory notes so the next instance of you resumes cleanly. Use
   memory_write("notes", ...) with the whole new body.
3. Cover, in this order: open threads with enough detail to continue; decisions
   and why; files touched with paths and any backup ids; dead ends; next
   actions ordered.
4. Prune anything already finished. Stay under the token budget.
5. Reply with one line: SHUTDOWN COMPLETE

Do not ask questions. Do not wait. The process dies either way.
"""


def bind(app):
    global _app
    _app = app


def flag_path():
    return os.path.join(config.paths().root, FLAG)


def _digest(text):
    return hashlib.sha1((text or "").encode("utf-8", "replace")).hexdigest()


def _notes():
    try:
        return memctl.read("notes")
    except Exception:
        return ""


def _graceful(reason):
    app = _app
    if app is None:
        return False
    before = _digest(_notes())
    try:
        msgs = list(app.history) + [{"role": "user", "content": PROMPT}]
        cfg = dict(app.cfg)
        cfg["confirm"] = False
        app.loop.run(msgs, app.model_var.get(), app.rt.platform.name,
                     max_steps=6, cfg=cfg)
    except Exception as exc:
        log("shutdown turn raised: %s" % exc)
        return False
    return _digest(_notes()) != before


def _fallback(reason):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = []
    app = _app
    for m in ((app.history if app else [])[-FALLBACK_TURNS:]):
        role = m.get("role")
        body = m.get("content")
        if not isinstance(body, str) or not body.strip():
            continue
        lines.append("- **%s**: %s" % (role, " ".join(body.split())[:400]))
    block = ("\n\n---\n\n## UNVERIFIED SHUTDOWN %s\n\nReason: %s. The summary turn "
             "did not complete. Raw tail below; treat as lossy.\n\n%s\n"
             % (stamp, reason, "\n".join(lines) or "(no history)"))
    try:
        memctl.write("notes", _notes() + block, "shutdown fallback")
    except Exception as exc:
        log("shutdown fallback failed: %s" % exc)
        try:
            p = os.path.join(config.paths().root, "shutdown-notes.md")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(block)
        except Exception:
            pass


def run(reason="user"):
    with _lock:
        if _state["running"] or _state["done"]:
            return False
        _state["running"] = True
    try:
        log("shutdown: %s" % reason)
        if not _graceful(reason):
            _fallback(reason)
    finally:
        with _lock:
            _state["done"] = True
            _state["running"] = False
    return True


def run_and_wait(reason="user", timeout=TIMEOUT):
    """Start shutdown, wait up to timeout, fall back if it overruns."""
    with _lock:
        if _state["running"] or _state["done"]:
            return False
    t = threading.Thread(target=run, args=(reason,), daemon=True, name="shutdown")
    t.start()
    t.join(timeout)
    if t.is_alive():
        log("shutdown overran %ss, writing fallback" % timeout)
        _fallback(reason + " (timeout)")
    return True


# ---- layer 3 ---------------------------------------------------------

def _console_handler(ctrl_type):
    if ctrl_type in (0, 1, 2, 5, 6):
        run_and_wait("console %d" % ctrl_type)
        return True
    return False


def _watch_flag(stop):
    while not stop.wait(1.0):
        p = flag_path()
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
            run_and_wait("quit flag")
            return


def arm():
    if _state["armed"]:
        return
    _state["armed"] = True
    if os.name == "nt":  # console ctrl handler is Windows-only; SIGTERM covers the rest
        try:
            handler = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)(_console_handler)
            _keepalive.append(handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
        except Exception as exc:
            log("console handler unavailable: %s" % exc)
    try:
        signal.signal(signal.SIGTERM, lambda *_: run_and_wait("sigterm"))
    except Exception:
        pass
    stop = threading.Event()
    threading.Thread(target=_watch_flag, args=(stop,), daemon=True,
                     name="quit-flag").start()
    atexit.register(lambda: None if _state["done"] else _fallback("atexit"))