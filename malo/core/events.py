"""Typed event names and a thread-safe bus. The UI drains; workers emit."""
import queue

DELTA = "delta"
THINK = "think"
TOOL = "tool"
TOOL_RESULT = "tool_result"
CONFIRM = "confirm"
ARTIFACT = "artifact"
TURN = "turn"
USAGE = "usage"
MODELS = "models"
ERROR = "error"
WAKE = "wake"
STATE = "state"


def ev(kind, **kw):
    kw["type"] = kind
    return kw


class Bus:
    def __init__(self):
        self._q = queue.Queue()

    def emit(self, event):
        self._q.put(event)

    def drain(self, handler):
        """Call handler for every queued event. Returns False when empty."""
        got = False
        while True:
            try:
                handler(self._q.get_nowait())
                got = True
            except queue.Empty:
                return got