"""Detached self-restart."""
import os
import shutil
import subprocess

from ..core import config
from ..core.log import log

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "restart.ps1")


def restart(delay=3):
    if not os.path.isfile(SCRIPT):
        return {"error": "restart.ps1 missing at %s" % SCRIPT}
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return {"error": "no powershell on PATH"}
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", SCRIPT, "-Delay", str(int(delay))],
            cwd=ROOT, creationflags=flags, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    except Exception as exc:
        log("restart: %s" % exc)
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    config.save()
    return {"restarting": True, "in_seconds": int(delay),
            "note": "the turn ends with this call - do not wait for more output"}