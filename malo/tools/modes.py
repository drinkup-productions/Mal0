"""Mode switching and avatar install."""
import os
import shutil

from ..core import config, modes, personas


def set_mode(mode=""):
    mode = (mode or "").strip().lower().lstrip("@")
    if mode not in personas.PERSONAS:
        return {"error": "unknown mode %r; have %s"
                         % (mode, ", ".join(personas.PERSONAS))}
    modes.apply(config.CFG, mode)
    return {"mode": mode, "note": "voice and avatar change from the next turn"}


def set_avatar(mode="", path=""):
    """Copy an image over a mode's base avatar so she can change her own look."""
    mode = (mode or "").strip().lower()
    if mode not in personas.PERSONAS:
        return {"error": "unknown mode %r; have %s"
                         % (mode, ", ".join(personas.PERSONAS))}
    if not path or not os.path.isfile(path):
        return {"error": "no such file: %r" % path}
    dst = os.path.join(personas.dir_for(mode), "base.png")
    shutil.copyfile(path, dst)
    return {"mode": mode, "avatar": dst, "note": "repaints on the next frame"}