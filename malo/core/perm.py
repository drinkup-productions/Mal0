"""Tool permission classes. One switch per class, not per tool."""
CLASS = {
    # read
    "read": "read", "tail": "read", "code_grep": "read", "list_windows": "read",
    "screen_shot": "read", "uia_tree": "read", "uia_find": "read",
    "undo_list": "read", "proposals": "read", "list_skills": "read", "list_apps": "read",
    "profile_list": "read", "profile_show": "read",
    # write
    "write": "write", "edit": "write", "undo": "write", "journal": "write",
    "remember": "write", "forget": "write", "write_skill": "write",
    "profile_use": "write", "profile_save": "write", "profile_delete": "write",
    "set_avatar": "write",
    # network
    "perchance_image": "network", "perchance_status": "network",
    # shell
    "bash": "shell", "run_tests": "shell",
    # input
    "mouse_move": "input", "click": "input", "scroll": "input", "key": "input",
    "type_text": "input", "uia_act": "input", "focus_window": "input",
    # system
    "notify": "system", "open_app": "system",
    # self-modification
    "propose": "selfedit", "apply": "selfedit",
}

DEFAULTS = {"read": True, "write": True, "shell": True, "input": True,
            "system": True, "network": True, "selfedit": False}


def cls(name):
    if "__" in str(name):
        return "network"
    return CLASS.get(name, "shell")


def allowed(name, cfg):
    grants = cfg.get("perm") or {}
    c = cls(name)
    return bool(grants.get(c, DEFAULTS.get(c, False)))


def report(cfg):
    grants = cfg.get("perm") or {}
    return ", ".join("%s=%s" % (k, "on" if grants.get(k, v) else "off")
                     for k, v in DEFAULTS.items())