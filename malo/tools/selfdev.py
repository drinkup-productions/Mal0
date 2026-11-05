"""Self-development tools. Read-only unless you call propose or apply."""
from ..core import config, selfdev


def code_grep(pattern, glob="*.py", limit=80):
    try:
        return selfdev.grep(pattern, glob, int(limit or 80))
    except Exception as exc:
        return {"error": str(exc)}


def run_tests(timeout=300):
    try:
        return selfdev.run_tests(int(timeout or 300))
    except Exception as exc:
        return {"error": str(exc)}


def propose(title, rationale, files):
    if config.get("self_edit") == "off":
        return {"error": "self-edit is off"}
    try:
        return selfdev.propose(title, rationale, files)
    except Exception as exc:
        return {"error": str(exc)}


def apply(pid, force=False):
    if config.get("self_edit") != "apply":
        return {"error": "self_edit is %r - set it to 'apply' first" % config.get("self_edit")}
    try:
        return selfdev.apply(pid, bool(force))
    except Exception as exc:
        return {"error": str(exc)}


def proposals():
    return selfdev.proposals()


def discard(pid):
    return selfdev.discard(pid)