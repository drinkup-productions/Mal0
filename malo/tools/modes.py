"""Mode switching as a tool."""
from ..core import config, modes, personas


def set_mode(mode=""):
    mode = (mode or "").strip().lower().lstrip("@")
    if mode not in personas.PERSONAS:
        return {"error": "unknown mode %r; have %s"
                         % (mode, ", ".join(personas.PERSONAS))}
    modes.apply(config.CFG, mode)
    return {"mode": mode, "note": "voice and avatar change from the next turn"}