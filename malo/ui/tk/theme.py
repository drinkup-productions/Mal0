BG = "#14121b"
PANEL = "#1e1b28"
BORDER = "#312c40"
FG = "#eae7f2"
MUTED = "#9a94ad"
ACCENT = "#8b5cf6"
BGS = {"bd-check": "#1d1a26", "bd-dark": "#12101a",
       "bd-lav": "#cfcae6", "bd-none": "#14121b"}

STATES = {
    "idle": {"label": "Idle", "l": 0, "r": 0, "icon": None, "col": "#8b5cf6"},
    "happy": {"label": "Happy", "l": 13, "r": -13, "icon": "music", "col": "#22c55e"},
    "thinking": {"label": "Thinking", "l": 7, "r": -17, "icon": "dots", "col": "#a855f7"},
    "working": {"label": "Working", "l": 15, "r": -15, "icon": "gear", "col": "#3b82f6"},
    "alert": {"label": "Alert", "l": 19, "r": -19, "icon": "bang", "col": "#f59e0b"},
    "confused": {"label": "Confused", "l": -17, "r": -7, "icon": "quest", "col": "#e8b923"},
    "sleepy": {"label": "Sleepy", "l": -25, "r": 25, "icon": "sleep", "col": "#6366f1"},
    "excited": {"label": "Excited", "l": 21, "r": -21, "icon": "star", "col": "#ec4899"},
    "error": {"label": "Error", "l": -21, "r": 21, "icon": "cross", "col": "#ef4444"},
    "done": {"label": "Done", "l": 15, "r": -15, "icon": "check", "col": "#10b981"},
}
GLYPH = {"music": "\u266a", "dots": "\u2026", "gear": "\u2699", "bang": "!", "quest": "?",
         "sleep": "z", "star": "\u2605", "cross": "\u2715", "check": "\u2713",
         "heart": "\u2665", "bulb": "\u263c", "bolt": "\u26a1"}
REACTIONS = ["bang", "quest", "heart", "star", "check", "cross", "bulb", "bolt"]