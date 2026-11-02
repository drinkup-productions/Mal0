"""Headless agent loop. Emits to a Bus; never imports a UI."""
import itertools
import json
import threading
from . import memory
from ..tools import registry
from . import events as E, ledger, log as _log, presence, prompt, provider
#from . core import autonomy
import concurrent.futures
import time

MAX_STEPS = 16


class Engine:
    def __init__(self, bus, cfg):
        self.bus = bus
        self.cfg = cfg
        self.stop = threading.Event()
        self.pending = {}
        self._ids = itertools.count(1)
        self.deadline = 0.0
        self._last_sig = None
        self._reps = 0

    def approve(self, pid, ok):
        slot = self.pending.get(pid)
        if slot:
            slot["ok"] = ok
            slot["ev"].set()

    def release(self):
        self.stop.set()
        for s in list(self.pending.values()):
            s["ev"].set()

    def run(self, messages, model, platform_name="windows", max_steps=MAX_STEPS):
        provider.set_model(model)
        presence.nudge(warmth=0.05)
        self.deadline = time.time() + float(self.cfg.get("turn_budget") or 240)
        self._last_sig, self._reps = None, 0
        prov = provider.build(self.cfg)
        last_user = next((m["content"] for m in reversed(messages)
                          if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        system = prompt.build(self.cfg, platform_name, last_user)
        convo = [{"role": "system", "content": system}] + messages
        n0 = len(convo)
        out = []
        try:
            self._loop(convo, prov, max_steps, out)
        except Exception as exc:
            _log.log("engine: %s" % exc)
            presence.nudge(restless=0.08, energy=-0.03)
            self.bus.emit(E.ev(E.ERROR, text="%s: %s" % (type(exc).__name__, exc)))
        finally:
            presence.nudge(energy=-0.02, focus=0.03)
            self.bus.emit(E.ev(E.TURN, messages=convo[n0:]))
            if last_user and out:
                threading.Thread(target=memory.extract,
                                 args=(self.cfg, last_user, "".join(out), prov, model),
                                 daemon=True).start()

    def _loop(self, convo, prov, max_steps, out):
        for _ in range(max_steps):
            if self.deadline and time.time() > self.deadline:
                self.bus.emit(E.ev(E.ERROR, text="turn budget exceeded"))
                return
            if self.stop.is_set():
                return
            text, calls, usage = "", {}, None
            for chunk in prov.stream(convo, registry.all_specs() if self.cfg.get("tools", True) else [],
                                     self.stop):
                if chunk.get("usage"):
                    usage = chunk["usage"]
                d = ((chunk.get("choices") or [{}])[0]).get("delta") or {}
                if d.get("reasoning_content"):
                    self.bus.emit(E.ev(E.THINK, text=d["reasoning_content"]))
                if d.get("content"):
                    text += d["content"]
                    out.append(d["content"])
                    self.bus.emit(E.ev(E.DELTA, text=d["content"]))
                for tc in (d.get("tool_calls") or []):
                    i = tc.get("index", 0)
                    slot = calls.setdefault(i, {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    slot["name"] = fn.get("name") or slot["name"]
                    slot["args"] += fn.get("arguments") or ""
            if usage:
                ledger.add(0.0, usage.get("total_tokens") or 0)
                self.bus.emit(E.ev(E.USAGE, session=ledger.SESSION["tokens"],
                                   prompt=usage.get("prompt_tokens") or 0))
            if not calls:
                return
            convo.append({"role": "assistant", "content": text or None,
                          "tool_calls": [{"id": c["id"], "type": "function",
                                          "function": {"name": c["name"],
                                                       "arguments": c["args"] or "{}"}}
                                         for c in calls.values()]})
            for c in calls.values():
                if self.stop.is_set():
                    return
                try:
                    args = json.loads(c["args"] or "{}")
                except Exception:
                    args = {}
                self.bus.emit(E.ev(E.TOOL, name=c["name"], args=args))
                if self.cfg.get("confirm") and c["name"] in registry.CONFIRM:
                    pid = next(self._ids)
                    slot = {"ev": threading.Event(), "ok": False}
                    self.pending[pid] = slot
                    self.bus.emit(E.ev(E.CONFIRM, id=pid, name=c["name"], args=args))
                    slot["ev"].wait(300)
                    self.pending.pop(pid, None)
                    if not slot["ok"]:
                        convo.append({"role": "tool", "tool_call_id": c["id"],
                                      "content": "Skipped by the user."})
                        self.bus.emit(E.ev(E.TOOL_RESULT, ok=True, text="skipped"))
                        continue
                sig = c["name"] + "\x00" + (c["args"] or "")
                if sig == self._last_sig:
                    self._reps += 1
                else:
                    self._last_sig, self._reps = sig, 0
                if self._reps >= 2:
                    self.bus.emit(E.ev(E.TOOL_RESULT, ok=True, text="identical call - reusing result"))
                    convo.append({"role": "tool", "tool_call_id": c["id"],
                                  "content": json.dumps({"note": "you already called this with "
                                                                 "identical arguments - use the earlier "
                                                                 "result and move on"})})
                    continue
                tmo = int(self.cfg.get("tool_timeout") or 120)
                ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                try:
                    result = ex.submit(registry.run, c["name"], args).result(timeout=tmo)
                except concurrent.futures.TimeoutError:
                    result = {"error": "tool timed out after %ds" % tmo}
                finally:
                    ex.shutdown(wait=False)
                ok = "error" not in result
                self.bus.emit(E.ev(E.TOOL_RESULT, ok=ok, text=json.dumps(result)[:600]))
                convo.append({"role": "tool", "tool_call_id": c["id"],
                              "content": json.dumps(result)[:6000]})
        self.bus.emit(E.ev(E.ERROR, text="stopped after %d rounds" % max_steps))