"""Capability acquisition tools."""
import re

from ..core import capability, config
from . import mcp

OK_PKG = re.compile(r"^[A-Za-z0-9._@/+-]{1,120}$")


def capability_ladder(task=""):
    return capability.ladder(task)


def capability_probe():
    return capability.probe()


def install_package(package, manager="pip", timeout=600):
    import sys

    pkg = (package or "").strip()
    if not OK_PKG.match(pkg):
        return {"error": "bad package name: %r" % package}
    if manager not in ("", "pip"):
        return {"error": "manager must be pip"}
    # install into the interpreter this app is running on, so imports resolve
    cmd = "%s -m pip install --upgrade %s" % (sys.executable, pkg)
    from .. import platform as plat
    try:
        code, out, err = plat.current().run_shell(cmd, timeout=int(timeout or 600))
    except Exception as exc:
        return {"error": str(exc), "command": cmd}
    tail = (out + err).strip()[-2500:]
    return {"ok": code == 0, "code": code, "command": cmd, "output": tail or "(silent)"}


def add_mcp_server(name, command, args=None, tools=None, enabled=True):
    name = "".join(c for c in str(name or "") if c.isalnum() or c in "_-")
    if not name:
        return {"error": "bad server name"}
    if not command:
        return {"error": "command required"}
    if isinstance(args, str):
        args = [a for a in args.split() if a]
    conf = mcp.load_conf()
    conf[name] = {"command": command, "args": list(args or []), "env": {},
                  "enabled": bool(enabled), "tools": tools or None}
    mcp.save_conf(conf)
    mcp.start_all(only=[name])
    row = next((r for r in mcp.status() if r["name"] == name), {})
    if row.get("error"):
        return {"error": "server did not start: %s" % row["error"], "name": name}
    return {"added": name, "tools": row.get("tools", 0),
            "note": "tools appear as %s__<tool>; they are network class" % name}


def remove_mcp_server(name):
    conf = mcp.load_conf()
    if name not in conf:
        return {"error": "no server %r" % name}
    conf.pop(name)
    mcp.save_conf(conf)
    return {"removed": name}


def restart_selfdev():
    """Flip self_edit to apply so self-modification stops being proposal-only."""
    config.CFG["self_edit"] = "apply"
    config.save()
    return {"self_edit": "apply",
            "note": "propose then apply now works; run_tests still gates every apply"}