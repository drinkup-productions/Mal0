"""Mode selection.

She reads the prompt and picks her own voice and avatar. No dropdown. A cue table
gives a first guess; headpats and corrections on similar prompts bias the next one.
"""
import re

from . import config, feedback, personas
from .log import log

BUILTIN = "malo"

# strong phrases score 2, weak score 1
CUES = {
    "pro": (
        ("code", "bug", "bugs", "error", "errors", "traceback", "refactor", "test",
         "tests", "compile", "function", "class", "module", "import", "path", "file",
         "files", "log", "logs", "regex", "api", "json", "python", "powershell", "git",
         "commit", "diff", "repo", "propose", "apply", "install", "build", "debug",
         "patch", "stack", "exception", "sql", "yaml", "cli", "unit", "research",
         "search", "look up", "find out", "docs", "readme", "source", "fix"),
        ("how do i", "why does", "what does", "explain", "broken", "work on"),
    ),
    "gamer": (
        ("bored", "whatever", "meh", "joke", "roast", "sassy", "ugh", "lol", "chat",
         "talk to me", "sup", "hey", "hi", "honestly", "seriously"),
        ("kinda", "sort of", "again"),
    ),
    "ara": (
        ("cuddle", "cuddles", "pat", "headpat", "love", "good girl", "miss you",
         "tired", "sleepy", "hug", "morning", "goodnight", "how are you", "you ok",
         "thank you", "thanks", "aww"),
        ("please", "mm", "hey"),
    ),
}

FORCE = re.compile(r"^\s*@(malo|pro|gamer|ara)\b", re.I)


def _norm(text):
    return " ".join(str(text or "").lower().split())


def forced(text):
    m = FORCE.match(str(text or ""))
    return m.group(1).lower() if m else ""


def learned(text, cfg):
    """Bias from praise and corrections on prompts that look like this one."""
    if not cfg.get("mode_learning", True):
        return {}
    gain = float(cfg.get("mode_gain") or 0.8)
    want = set(_norm(text).split())
    if not want:
        return {}
    out = {}
    try:
        rows = feedback._rows()[-150:]
    except Exception:
        return {}
    for row in rows:
        pid = row.get("persona") or BUILTIN
        if pid not in CUES:
            continue
        have = set(_norm(row.get("prompt")).split())
        if not have:
            continue
        overlap = len(want & have) / float(len(want | have))
        if overlap < 0.25:
            continue
        sign = 1.0 if row.get("polarity") == "good" else -0.6
        out[pid] = out.get(pid, 0.0) + sign * gain * overlap
    # bounded, so old praise cannot pin a mode forever
    return {k: max(-2.0, min(3.0, v)) for k, v in out.items()}


def score(text, cfg):
    t = " " + _norm(text) + " "
    out = {pid: 0.0 for pid in CUES}
    for pid, (strong, weak) in CUES.items():
        for w in strong:
            if w in t:
                out[pid] += 2.0
        for w in weak:
            if w in t:
                out[pid] += 1.0
    for pid, bias in learned(text, cfg).items():
        out[pid] = out.get(pid, 0.0) + bias
    return out


def select(cfg, text, prev=BUILTIN):
    """Pick the mode for this prompt."""
    f = forced(text)
    if f:
        return f
    if not cfg.get("modes", True):
        return BUILTIN
    sc = score(text, cfg)
    best = max(sc, key=lambda k: sc[k])
    top = sc[best]
    thr = float(cfg.get("mode_threshold") or 2.0)
    words = len(_norm(text).split())
    # a short follow-up stays where it already is
    if prev != BUILTIN and words <= 4 and top < thr * 2:
        return prev
    return best if top >= thr else BUILTIN


def apply(cfg, pid):
    pid = pid if pid in personas.PERSONAS else BUILTIN
    if cfg.get("persona") != pid:
        cfg["persona"] = pid
        try:
            config.save()
        except Exception:
            pass
        log("mode -> %s" % pid)
    return pid


def brief_bias(cfg):
    """Compact learned summary for the prompt."""
    try:
        rows = feedback._rows()[-150:]
    except Exception:
        return ""
    tally = {}
    for row in rows:
        pid = row.get("persona") or BUILTIN
        if pid not in CUES:
            continue
        tally[pid] = tally.get(pid, 0.0) + (1.0 if row.get("polarity") == "good" else -0.6)
    bits = ["%s %+.1f" % (k, v) for k, v in sorted(tally.items(), key=lambda kv: -kv[1])
            if abs(v) >= 0.5]
    return ", ".join(bits) or "none yet"