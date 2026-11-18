"""The escalation ladder. Nothing is impossible, only unbuilt.

Gives the agent an ordered list of ways to get a capability it does not
have, instead of letting it report "I can't" and stop.
"""
import os
import shutil

from . import config

RUNGS = (
    ("existing tool", "Something you already have does this. Search before "
                      "deciding otherwise: code_grep your own specs, list_skills, "
                      "check the mcp tools."),
    ("compose", "Two existing tools chained: bash writes, read verifies, a job "
                "carries it. Most 'new' tasks are a composition, not a new tool."),
    ("skill", "Write a skill with write_skill(name, code). SPECS plus matching "
              "functions. It is live on the next turn. This is the cheap, "
              "reversible way to add a real tool."),
    ("shell", "bash() reaches everything on the machine: pip, node, git, winget, "
              "net. If a program exists, call it. If a library exists, import it "
              "from a skill."),
    ("install", "install_package() puts a library or CLI on the box, then use it. "
                "Prefer pip for python, winget for applications."),
    ("mcp", "add_mcp_server() attaches an external MCP server, and its tools "
            "appear as name__tool. Best for browsers, APIs and anything with a "
            "maintained implementation."),
    ("self-edit", "propose() then apply() changes your own source. Required for "
                  "anything the skill loader cannot express: a new core tool, a "
                  "window change, a permission class."),
    ("ask", "Only after the six above: say which rung failed and why, and ask "
            "for the one thing only the user can supply."),
)


def ladder(task=""):
    rows = ["%d. %s - %s" % (i + 1, name, text)
            for i, (name, text) in enumerate(RUNGS)]
    return {"task": task or "(unnamed)",
            "rungs": "\n".join(rows),
            "rule": "Work down the ladder. Report the rung you are on, not the "
                    "task you cannot do. 'I can't' is only valid after rung 8.",
            "backups": "Every write, edit, skill and shell call is snapshotted "
                       "first. backup_list to see them, backup_restore to go back."}


def probe():
    """What is actually available right now."""
    out = {}
    for exe in ("python", "pip", "node", "npx", "uvx", "git", "winget",
                "powershell", "pwsh"):
        out[exe] = bool(shutil.which(exe))
    cfg = config.CFG
    out["self_edit"] = cfg.get("self_edit")
    out["repo"] = cfg.get("repo") or ""
    out["workspace"] = cfg.get("workspace") or ""
    out["perm"] = cfg.get("perm") or {}
    try:
        from ..tools import mcp
        out["mcp"] = ["%s:%s" % (r["name"], "up" if r["ready"] else r["error"] or "off")
                      for r in mcp.status()]
    except Exception as exc:
        out["mcp"] = ["probe failed: %s" % exc]
    try:
        from . import skills
        out["skills"] = len(skills.SPECS)
    except Exception:
        out["skills"] = 0
    out["next"] = ("capability_ladder for the ordered plan; self_edit must be "
                   "'apply' before apply() will install anything")
    return out