"""Config load/save plus the default table. No platform imports beyond paths."""
import json
import os

from .. import platform as plat
from .log import log

OLD_TEST_CMD = "python -m compileall -q malo"

DEFAULT_CFG = {
    # backend
    "provider": "openai_compat",
    "base_url": "http://127.0.0.1:1234/v1",
    "api_key": "",
    "model": "",
    "temperature": 0.7,
    "ctx": 0,
    "preset": "local",
    "tools": True,
    # letta loop
    "letta": False,
    "letta_url": "ws://127.0.0.1:4500",
    "letta_mode": "standard",
    "letta_builtin_tools": False,
    "letta_agents": {},
    # behaviour
    "persona": "malo",
    "confirm": True,
    "workspace": "",
    "allow_roots": [],
    "profiles": {},
    "active_profile": "",
    "perm": {},
    "background": "bd-lav",
    "idle": True,
    "idle_evolve": True,
    "idle_evolve_minutes": 10,
    "budget_day": 0.0,
    # audio
    "sfx": True,
    "sfx_volume": 80,
    "sfx_headpat": "headpat.mp3",
    "sfx_goodgirl": "goodgirl.mp3",
    "sfx_error": "",
    "sfx_treat": "",
    # memory
    "memory": True,
    "memory_extract": True,
    "memory_limit": 10,
    "memory_budget": 1800,
    # autonomy
    "autonomy": True,
    "autonomy_idle_secs": 600,
    "autonomy_cooldown_secs": 1800,
    "autonomy_max_per_day": 12,
    "wake_brief": "",
    "turn_budget": 0,
    "turn_result_budget": 30000,
    "tool_timeout": 120,
    "presence": True,
    "presence_min_gap": 600,
    "presence_max_gap": 5400,
    "web_token": "",
    "repo": "",
    "self_edit": "propose",
    "self_test_cmd": "python -m unittest discover -s tests -t . -q",
    "selfdev_idle_secs": 1800,
    "selfdev_cooldown_secs": 3600,
    "selfdev_max_per_day": 6,
}

CFG = {}
_paths = None

PRESETS = {"local": "http://127.0.0.1:1234/v1",
           "freellmapi": "http://127.0.0.1:3001/v1",
           "custom": ""}


def paths():
    global _paths
    if _paths is None:
        _paths = plat.current().paths()
    return _paths


def load():
    """Load config, migrating the pre-split lmstudio_url key."""
    CFG.clear()
    CFG.update(DEFAULT_CFG)
    CFG["workspace"] = CFG["workspace"] or paths().workspace_default
    p = paths().config
    try:
        with open(p, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except Exception:
        return CFG
    if isinstance(raw, dict):
        if "lmstudio_url" in raw and "base_url" not in raw:
            raw["base_url"] = str(raw["lmstudio_url"]).rstrip("/") + "/v1"
        CFG.update({k: v for k, v in raw.items() if k in DEFAULT_CFG})
    if CFG.get("self_test_cmd") == OLD_TEST_CMD:
        CFG["self_test_cmd"] = DEFAULT_CFG["self_test_cmd"]
    return CFG


def save():
    try:
        with open(paths().config, "w", encoding="utf-8") as fh:
            json.dump(CFG, fh, indent=2)
    except Exception as exc:
        log("config save failed: %s" % exc)


def get(key, default=None):
    return CFG.get(key, default)


def reset():
    global _paths
    _paths = None
    CFG.clear()