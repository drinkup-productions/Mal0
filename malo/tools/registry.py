"""Tool specs, dispatch and the confirm set."""
from . import android as atools, core, mcp, selfdev as sdev, vision
from ..platform import current

CONFIRM = {"write", "edit", "bash"}
DESKTOP_ONLY = {"screen_shot", "list_windows", "focus_window"}

IMPL = {
    "read": core.read, "tail": core.tail, "write": core.write, "edit": core.edit,
    "bash": core.bash, "remember": core.remember, "forget": core.forget,
    "undo": core.undo, "undo_list": core.undo_list, "journal": core.journal,
    "screen_shot": vision.screen_shot, "list_windows": vision.list_windows,
    "focus_window": vision.focus_window, "notify": vision.notify,
    "open_app": atools.open_app, "list_apps": atools.list_apps,
    "code_grep": sdev.code_grep, "run_tests": sdev.run_tests,
    "propose": sdev.propose, "apply": sdev.apply, "proposals": sdev.proposals,
}


def _spec(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


CORE_SPECS = [
    _spec("read", "Read a file with line numbers, or list a directory.",
          {"path": {"type": "string"},
           "offset": {"type": "integer", "description": "First line, 1-based."},
           "limit": {"type": "integer", "description": "How many lines. Default 400."}},
          ["path"]),
    _spec("tail", "Return the last N lines of a file. Use this for logs.",
          {"path": {"type": "string"},
           "n": {"type": "integer", "description": "How many lines. Default 40."}},
          ["path"]),
    _spec("write", "Create or overwrite a whole file.",
          {"path": {"type": "string"}, "content": {"type": "string"}},
          ["path", "content"]),
    _spec("edit", "Replace one block of text. 'old' must appear exactly once.",
          {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
          ["path", "old", "new"]),
    _spec("bash", "Run a shell command. Returns exit code, stdout, stderr.",
          {"command": {"type": "string"}, "cwd": {"type": "string"},
           "timeout": {"type": "integer"}},
          ["command"]),
    _spec("remember", "Append one durable fact about the user to your notes.",
          {"text": {"type": "string"}}, ["text"]),
    _spec("forget", "Delete a memory by id, or by matching text.",
          {"id": {"type": "integer"}, "text": {"type": "string"}}, []),
    _spec("journal", "Leave a note for your future self. Survives restarts.",
          {"text": {"type": "string"}}, ["text"]),
    _spec("undo", "Restore a file from the last snapshot. 0 is the most recent.",
          {"index": {"type": "integer", "description": "How far back. Default 0."}}, []),
    _spec("undo_list", "List recent file snapshots with their age.",
          {"limit": {"type": "integer"}}, []),
    _spec("screen_shot", "Capture a monitor to a PNG. Returns the file path.",
          {"monitor": {"type": "integer", "description": "Monitor index, default 0."},
           "scale": {"type": "number", "description": "0.1-1.0, default 0.5."}}, []),
    _spec("list_windows", "List visible top-level windows: hwnd, title, process.",
          {"limit": {"type": "integer", "description": "Max rows, default 60."}}, []),
    _spec("focus_window", "Bring a window to the foreground by hwnd.",
          {"hwnd": {"type": "integer"}}, ["hwnd"]),
    _spec("notify", "Raise a desktop notification.",
          {"title": {"type": "string"}, "text": {"type": "string"}}, ["title"]),
    _spec("code_grep", "Regex search over your own source. Read-only.",
          {"pattern": {"type": "string"}, "glob": {"type": "string"},
           "limit": {"type": "integer"}}, ["pattern"]),
    _spec("run_tests", "Run the self-test command against your source.",
          {"timeout": {"type": "integer"}}, []),
    _spec("propose", "Write a self-edit proposal. files maps repo path -> full new content.",
          {"title": {"type": "string"}, "rationale": {"type": "string"},
           "files": {"type": "object"}}, ["title", "rationale", "files"]),
    _spec("apply", "Install a proposal, snapshot originals, run tests, revert on failure.",
          {"pid": {"type": "string"}}, ["pid"]),
    _spec("proposals", "List pending proposals.", {}, []),
]

ANDROID_SPECS = [
    _spec("open_app", "Launch an app. Accepts a package name or a fragment like 'youtube'.",
          {"package": {"type": "string"}}, ["package"]),
    _spec("list_apps", "List installed third-party package names.",
          {"limit": {"type": "integer"}}, []),
]


def all_specs():
    name = current().name
    specs = list(CORE_SPECS)
    if name == "android":
        specs += ANDROID_SPECS
    if name != "windows":
        specs = [s for s in specs if s["function"]["name"] not in DESKTOP_ONLY]
    return specs + mcp.tool_specs()


def run(name, args):
    try:
        if name in IMPL:
            return IMPL[name](**(args or {}))
        if "__" in name:
            return mcp.call(name, args or {})
        return {"error": "unknown tool " + name}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}