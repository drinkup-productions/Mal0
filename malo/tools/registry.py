"""Tool specs, dispatch and the confirm set."""
from . import (android as atools, core, input as itools, mcp, modes as mtools,
               perchance, profiles as ptools, screen, selfdev as sdev,
               skills as stools, uia, vision)
from ..core import config, perm, skills
from ..platform import current

CONFIRM = {"write", "edit", "bash"}
DESKTOP_ONLY = {"screen_shot", "list_windows", "focus_window",
                "mouse_move", "click", "scroll", "key", "type_text",
                "uia_tree", "uia_find", "uia_act"}

IMPL = {
    "read": core.read, "tail": core.tail, "write": core.write, "edit": core.edit,
    "bash": core.bash, "remember": core.remember, "forget": core.forget,
    "undo": core.undo, "undo_list": core.undo_list, "journal": core.journal,
    "screen_shot": vision.screen_shot, "list_windows": vision.list_windows,
    "focus_window": vision.focus_window, "notify": vision.notify,
    "mouse_move": itools.mouse_move, "click": itools.click, "scroll": itools.scroll,
    "key": itools.key, "type_text": itools.type_text,
    "uia_tree": uia.tree, "uia_find": uia.find, "uia_act": uia.act,
    "open_app": atools.open_app, "list_apps": atools.list_apps,
    "code_grep": sdev.code_grep, "run_tests": sdev.run_tests,
    "propose": sdev.propose, "apply": sdev.apply, "proposals": sdev.proposals,
    "discard": sdev.discard,
    "write_skill": stools.write_skill, "list_skills": stools.list_skills,
    "reload_skills": stools.reload_skills,
    "profile_list": ptools.profile_list, "profile_show": ptools.profile_show,
    "profile_use": ptools.profile_use, "profile_save": ptools.profile_save,
    "profile_delete": ptools.profile_delete,
    "set_mode": mtools.set_mode,
    "set_avatar": mtools.set_avatar,
    "perchance_image": perchance.perchance_image,
    "perchance_status": perchance.perchance_status,
    "perchance_debug": perchance.perchance_debug,
    "screen_look": screen.look, "screen_find": screen.find,
    "screen_click": screen.click_text, "screen_wait": screen.wait_for,
    "screen_read": screen.read,
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
    _spec("list_windows", "List visible top-level windows: hwnd, title, process. "
                          "Filtered by the active workspace profile unless all_profiles.",
          {"limit": {"type": "integer", "description": "Max rows, default 60."},
           "all_profiles": {"type": "boolean", "description": "Ignore the profile filter."}},
          []),
    _spec("focus_window", "Bring a window to the foreground by hwnd.",
          {"hwnd": {"type": "integer"}}, ["hwnd"]),
    _spec("notify", "Raise a desktop notification.",
          {"title": {"type": "string"}, "text": {"type": "string"}}, ["title"]),
    _spec("mouse_move", "Move the real cursor to x, y.",
          {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
    _spec("click", "Click the mouse, optionally at x, y first.",
          {"x": {"type": "integer"}, "y": {"type": "integer"},
           "button": {"type": "string", "description": "left, right or middle."},
           "double": {"type": "boolean"}}, []),
    _spec("scroll", "Scroll the wheel. Positive is up.", {"amount": {"type": "integer"}}, []),
    _spec("key", "Press keys, space separated, e.g. 'ctrl s' or 'enter'.",
          {"keys": {"type": "string"}}, ["keys"]),
    _spec("type_text", "Type a string into the focused window.",
          {"text": {"type": "string"}}, ["text"]),
    _spec("uia_tree", "Dump the control tree of a window: index, role, name, class, rect. "
                      "Indexes feed uia_act.",
          {"hwnd": {"type": "integer", "description": "Window handle; omit for the foreground."},
           "depth": {"type": "integer", "description": "1-8, default 3."},
           "limit": {"type": "integer", "description": "Max elements, default 200."}}, []),
    _spec("uia_find", "Find controls by name fragment. Use the returned index with uia_act.",
          {"name": {"type": "string"},
           "hwnd": {"type": "integer"}, "depth": {"type": "integer"},
           "limit": {"type": "integer"}}, ["name"]),
    _spec("uia_act", "Act on an element from the last uia_tree or uia_find.",
          {"index": {"type": "integer"},
           "action": {"type": "string", "description": "click, value, focus, keys or read."},
           "value": {"type": "string"}}, []),
    _spec("code_grep", "Regex search over your own source. Read-only.",
          {"pattern": {"type": "string"}, "glob": {"type": "string"},
           "limit": {"type": "integer"}}, ["pattern"]),
    _spec("run_tests", "Run the self-test command against your source.",
          {"timeout": {"type": "integer"}}, []),
    _spec("propose", "Write a self-edit proposal. files maps repo path -> full new content.",
          {"title": {"type": "string"}, "rationale": {"type": "string"},
           "files": {"type": "object"}}, ["title", "rationale", "files"]),
    _spec("apply", "Install a proposal, snapshot originals, run tests, revert on failure.",
          {"pid": {"type": "string"},
           "force": {"type": "boolean", "description": "Reapply despite drift or a prior apply."}},
          ["pid"]),
    _spec("proposals", "List pending proposals.", {}, []),
    _spec("discard", "Delete a proposal without applying it.",
          {"pid": {"type": "string"}}, ["pid"]),
    _spec("write_skill", "Create or replace a skill module defining SPECS and its functions.",
          {"name": {"type": "string"}, "code": {"type": "string"}}, ["name", "code"]),
    _spec("list_skills", "List installed skills and any that failed to load.", {}, []),
    _spec("reload_skills", "Reload skills from disk.", {}, []),
    _spec("profile_list", "List workspace profiles and which one is active.", {}, []),
    _spec("profile_show", "Show one profile's roots, window filter and brief.",
          {"name": {"type": "string"}}, []),
    _spec("profile_use", "Switch workspace profile. Rewrites the jail and the wake brief.",
          {"name": {"type": "string"}}, ["name"]),
    _spec("profile_save", "Create or update a profile. roots and windows are ';' separated.",
          {"name": {"type": "string"}, "roots": {"type": "string"},
           "windows": {"type": "string"}, "brief": {"type": "string"}}, ["name"]),
    _spec("profile_delete", "Delete a profile.",
          {"name": {"type": "string"}}, ["name"]),
    _spec("set_mode", "Change your own voice and avatar. Modes: malo, pro, gamer, ara.",
          {"mode": {"type": "string"}}, ["mode"]),
    _spec("set_avatar", "Install an image file as a mode's avatar. Pair with "
                        "perchance_image.",
          {"mode": {"type": "string"}, "path": {"type": "string"}}, ["mode", "path"]),
    _spec("perchance_image", "Generate an avatar with the Perchance furry generator. "
                             "Drives a real Chrome window. Pass mode to install it directly.",
          {"prompt": {"type": "string"}, "mode": {"type": "string"},
           "style": {"type": "string"}, "ratio": {"type": "string"},
           "timeout": {"type": "integer"}}, ["prompt"]),
    _spec("perchance_status", "Check whether the generator browser is reachable.", {}, []),
    _spec("perchance_debug", "Dump the generator page's editable controls and "
                             "shadow roots. Use when a perchance lookup fails.", {}, []),
    _spec("screen_look", "Capture and OCR the screen. Returns text with centre "
                         "coordinates so you can click what you see.",
          {"monitor": {"type": "integer"}, "limit": {"type": "integer"}}, []),
    _spec("screen_find", "Locate one on-screen label. Returns its coordinates.",
          {"text": {"type": "string"}, "exact": {"type": "boolean"}}, ["text"]),
    _spec("screen_click", "Click an on-screen label by its text.",
          {"text": {"type": "string"}, "exact": {"type": "boolean"}}, ["text"]),
    _spec("screen_wait", "Wait until a label appears on screen.",
          {"text": {"type": "string"}, "timeout": {"type": "integer"}}, ["text"]),
    _spec("screen_read", "OCR one rectangle of the screen.", 
          {"x": {"type": "integer"}, "y": {"type": "integer"},
           "w": {"type": "integer"}, "h": {"type": "integer"}}, ["x", "y", "w", "h"]),
]

ANDROID_SPECS = [
    _spec("open_app", "Launch an app. Accepts a package name or a fragment like 'youtube'.",
          {"package": {"type": "string"}}, ["package"]),
    _spec("list_apps", "List installed third-party package names.",
          {"limit": {"type": "integer"}}, []),
]


def all_specs():
    name = current().name
    specs = list(CORE_SPECS) + skills.specs()
    if name == "android":
        specs += ANDROID_SPECS
    if name != "windows":
        specs = [s for s in specs if s["function"]["name"] not in DESKTOP_ONLY]
    return specs + mcp.tool_specs()


def run(name, args):
    try:
        if not perm.allowed(name, config.CFG):
            return {"error": "permission denied: %s is a %s-class tool and %s is off"
                    % (name, perm.cls(name), perm.cls(name))}
        if name in IMPL:
            return IMPL[name](**(args or {}))
        if name in skills.FUNCS:
            return skills.call(name, args or {})
        if "__" in name:
            return mcp.call(name, args or {})
        return {"error": "unknown tool " + name}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}