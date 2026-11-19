"""Restart surfaces."""
import os
import subprocess

from ..core.log import log

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "restart.sh")

_LOOP = None


def bind(loop):
    global _LOOP
    _LOOP = loop


def restart_worker():
    if _LOOP is None:
        return {"error": "no loop bound"}
    if _LOOP.restart():
        return {"restarting": "worker",
                "note": "the turn ends here - stop writing, the session resumes"}
    return {"error": "worker not running"}


def restart_app(delay=3):
    if not os.path.isfile(SCRIPT):
        return {"error": "restart.sh missing"}
    try:
        # start_new_session detaches the relauncher from our process group so it
        # survives when this app exits mid-shutdown (the Windows creationflags did
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP).
        subprocess.Popen(["/bin/sh", SCRIPT, str(int(delay))],
                         cwd=ROOT, start_new_session=True, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception as exc:
        log("restart_app: %s" % exc)
        return {"error": str(exc)}
    return {"restarting": "app", "in_seconds": int(delay)}