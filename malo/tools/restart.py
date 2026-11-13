"""Restart surfaces."""
import os
import shutil
import subprocess

from ..core.log import log

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "restart.ps1")

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
        return {"error": "restart.ps1 missing"}
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return {"error": "no powershell"}
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([shell, "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-File", SCRIPT, "-Delay", str(int(delay))],
                         cwd=ROOT, creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception as exc:
        log("restart_app: %s" % exc)
        return {"error": str(exc)}
    return {"restarting": "app", "in_seconds": int(delay)}