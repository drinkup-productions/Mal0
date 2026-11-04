"""Letta App Server client.

Letta owns the turn loop, retries, compaction and memory. MalO owns the tools:
every tool is registered as a controller-owned external tool and dispatched
through registry.run, so the jail, the permission classes and the confirm gate
still apply.
"""
import asyncio
import itertools
import json
import re
import threading
import time

from . import config, events as E, memory, personas, perm, presence, profiles, prompt, tasks
from .log import log

try:
    import websockets
except Exception:
    websockets = None

RECONNECT = 3.0
START_TIMEOUT = 30.0
NOISY = ("waiting_on_input",)
MAX_REFUSE = 2

# Stop reasons that mean the turn is still running.
CONTINUE = ("requires_approval", "executing_client_side_tool", "waiting_on_approval")
# Stop reasons that mean the turn is over and state should be reset.
TERMINAL = ("end_turn", "stop", "max_steps", "error", "cancelled", "aborted")

_TAG = re.compile(r"<tool_call>.*?(?:</tool_call>|$)|<function_call>.*?(?:</function_call>|$)",
                  re.S | re.I)


def _safe(name):
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in str(name))


def _text_of(content):
    """Assistant content arrives as a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text" or "text" in b:
                    out.append(str(b.get("text") or ""))
            elif isinstance(b, str):
                out.append(b)
        return "".join(out)
    return "" if content is None else str(content)


def _clean(text):
    """Drop tool-call markup the model wrote as prose."""
    if "<tool_call" in text or "<function_call" in text:
        return _TAG.sub("", text).rstrip()
    return text


def _norm(text):
    return " ".join(text.split()).lower()


def _tool_specs():
    from ..tools import registry
    tools, names = [], {}
    for s in registry.all_specs():
        f = s.get("function") or {}
        raw = f.get("name")
        if not raw:
            continue
        safe = _safe(raw)
        names[safe] = raw
        tools.append({
            "name": safe,
            "label": safe,
            "description": f.get("description") or raw,
            "parameters": f.get("parameters") or {"type": "object", "properties": {}},
        })
    return tools, names


def _persona_blocks(cfg):
    pid = personas.active(cfg)
    p = personas.PERSONAS.get(pid) or {}
    return pid, [
        {"label": "persona", "value": (
            "You are MalO: a purple-furred anthro wolf girl with a long spiky lavender "
            "mane, a white bone skull mask, a white cropped tank, black cargo shorts and "
            "two fluffy tails. Curious, a little eerie, quietly fond of the user. "
            "Your voice and priorities are set per turn by the MODE block; you are the "
            "same person in a different register.")},
        {"label": "human", "value": "The user owns this machine and runs you on it."},
    ]


def _system(cfg):
    try:
        base = prompt.build(cfg, "windows", "")
    except Exception as exc:
        log("prompt build failed: %s" % exc)
        base = "You are MalO, a program living on the user's Windows machine."
    return base + (
        "\n\nTOOL CALLING\n"
        "You act with tools. Prose on its own is a failure. After every tool result, "
        "read it; if it reports an error or says the user declined, say so plainly and "
        "stop. Never claim a file exists unless a write or edit result confirmed it. "
        "Do not repeat an identical call in the same turn.\n"
        "If the user declines an approval, the call did not run. Acknowledge and stop.\n"
    )


def _context(cfg, text):
    """Per-turn state preamble. The system prompt holds the static guide."""
    bits = ["[context]"]
    bits.append("permissions: " + perm.report(cfg))
    pid = personas.active(cfg)
    bits.append("mode: %s (%s) - change it if the work changes"
                % (pid, (personas.PERSONAS.get(pid) or {}).get("blurb") or ""))
    bits.append("state: " + presence.fragment())
    t = tasks.current()
    if t["text"]:
        bits.append("current task: " + t["text"][:300])
    j = presence.journal_read(3)
    if j:
        bits.append("your journal (background, not a queue):\n" + j)
    prof = profiles.active_name()
    if prof != profiles.BUILTIN:
        bits.append("profile: %s, roots: %s" % (prof, "; ".join(profiles.roots())))
    if cfg.get("memory", True):
        try:
            rows = memory.recall(text, int(cfg.get("memory_limit") or 10),
                                 budget=int(cfg.get("memory_budget") or 1800))
            block = memory.format_rows(rows)
            if block:
                bits.append("your memory (cite [kind:id], delete with forget):\n" + block)
        except Exception as exc:
            log("letta context memory: %s" % exc)
    bits.append("[/context]")
    return "\n".join(bits)


class Chat:
    def __init__(self, bus, cfg):
        self.bus = bus
        self.cfg = cfg
        self.pending = {}
        self._ids = itertools.count(1)
        self._names = {}
        self._emitted = {}
        self._turn_norm = []
        self._turn_had_tool = False
        self._tagged = False
        self._tag_retry = False
        self._last_status = ""
        self._answered = set()
        self._denied = set()
        self._refused = {}
        self._done = {}
        self._loop = None
        self._ws = None
        self._runtime = None
        self._thread = None
        self._reader = None
        self._started = None
        self._ready = threading.Event()
        self._closed = threading.Event()

    # -- lifecycle -----------------------------------------------------
    def start(self, timeout=START_TIMEOUT + 10):
        if websockets is None:
            self.bus.emit(E.ev(E.ERROR, text="websockets not installed"))
            return False
        if self._thread and self._thread.is_alive():
            return self._runtime is not None
        self._thread = threading.Thread(target=self._thread_main, daemon=True,
                                        name="letta")
        self._thread.start()
        self._ready.wait(timeout)
        return self._runtime is not None

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:
            log("letta: %s" % exc)
            self.bus.emit(E.ev(E.ERROR, text="letta: %s: %s" % (type(exc).__name__, exc)))
        finally:
            self._ready.set()
            try:
                self._loop.close()
            except Exception:
                pass

    async def _main(self):
        url = self.cfg.get("letta_url") or "ws://127.0.0.1:4500"
        while not self._closed.is_set():
            try:
                async with websockets.connect(url, max_size=None) as ws:
                    self._ws = ws
                    self._started = asyncio.Event()
                    self._answered.clear()
                    self._denied.clear()
                    self._refused.clear()
                    self._reader = asyncio.create_task(self._pump(ws))
                    try:
                        ok = await self._start_runtime()
                    finally:
                        self._ready.set()
                    if not ok:
                        self._reader.cancel()
                        return
                    await self._reader
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self._closed.is_set():
                    return
                log("letta connection: %s" % exc)
                self.bus.emit(E.ev(E.ERROR, text="letta disconnected: %s" % exc))
                await asyncio.sleep(RECONNECT)
            finally:
                self._ws = None
                self._runtime = None

    def close(self):
        self._closed.set()
        if self._reader and self._loop:
            self._loop.call_soon_threadsafe(self._reader.cancel)
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._abort(), self._loop)

    async def _abort(self):
        try:
            if self._ws and self._runtime:
                await self._ws.send(json.dumps({"type": "abort_message",
                                                "request_id": "abort-close",
                                                "runtime": self._runtime}))
        except Exception:
            pass

    def approve(self, pid, ok):
        slot = self.pending.get(pid)
        if slot:
            slot["ok"] = ok
            slot["ev"].set()

    def stop_turn(self):
        for slot in list(self.pending.values()):
            slot["ok"] = False
            slot["ev"].set()
        self.pending.clear()
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._abort(), self._loop)

    def busy(self):
        """True while an approval is outstanding."""
        return bool(self.pending)

    def _spawn(self, coro, label):
        task = asyncio.create_task(coro)

        def _done(fut):
            exc = fut.exception()
            if exc:
                log("letta task %s failed: %s: %s" % (label, type(exc).__name__, exc))

        task.add_done_callback(_done)
        return task

    @staticmethod
    def _sig(name, args):
        return name + "\x00" + json.dumps(args, sort_keys=True, default=str)

    def _refuse_message(self, sig):
        n = self._refused.get(sig, 0)
        if n <= 1:
            return "the user declined this call - it did NOT run. Say so and stop."
        return ("the user declined this call again - it did NOT run. Stop calling tools "
                "and answer the user with one sentence.")

    # -- runtime -------------------------------------------------------
    async def _start_runtime(self):
        tools, self._names = _tool_specs()
        self.bus.emit(E.ev(E.THINK, text="registering %d tools" % len(tools)))
        pid, blocks = _persona_blocks(self.cfg)
        agent_id = (self.cfg.get("letta_agents") or {}).get("main")
        frame = {
            "type": "runtime_start",
            "request_id": "start-%d" % int(time.time() * 1000),
            "cwd": self.cfg.get("workspace"),
            "mode": self.cfg.get("letta_mode") or "standard",
            "client_info": {"name": "malo", "title": "MalO", "version": "1.0"},
            "external_tools": [{"tools": tools}],
        }
        if agent_id:
            frame["agent_id"] = agent_id
            frame["create_conversation"] = {"body": {}}
        else:
            body = {"name": "MalO " + pid,
                    "system": _system(self.cfg),
                    "memory_blocks": blocks,
                    "model_settings": {
                        "temperature": float(self.cfg.get("letta_temperature") or 0.3)}}
            model = (self.cfg.get("letta_model") or "").strip()
            if model:
                body["model"] = model
                body["llm_config"] = {"model": model.split("/")[-1],
                                      "model_endpoint_type": "lmstudio_openai"}
            frame["create_agent"] = {"body": body}
            frame["create_conversation"] = {"body": {}}
        await self._ws.send(json.dumps(frame))
        try:
            await asyncio.wait_for(self._started.wait(), START_TIMEOUT)
        except asyncio.TimeoutError:
            self.bus.emit(E.ev(E.ERROR, text="letta runtime_start timed out"))
            return False
        return self._runtime is not None

    # -- turn ----------------------------------------------------------
    def send(self, text):
        if not self._loop or not self._ws or not self._runtime:
            return False
        asyncio.run_coroutine_threadsafe(self._input(text), self._loop)
        return True

    async def _input(self, text, no_tools=False, keep_task=False, is_retry=False):
        if not keep_task:
            tasks.begin(text)
        presence.nudge(warmth=0.05, focus=0.03)
        self._emitted.clear()
        self._turn_norm.clear()
        self._turn_had_tool = False
        self._tagged = False
        self._last_status = ""
        if not is_retry:
            self._tag_retry = False
        if not self._names:
            _, self._names = _tool_specs()
            log("letta tool list was empty - rebuilt %d specs" % len(self._names))
        body = _context(self.cfg, text) + "\n\n" + text
        payload = {
            "kind": "create_message",
            "messages": [{"role": "user", "content": body,
                          "client_message_id": "m%d" % next(self._ids)}],
            "exclude_interactive_tools": True,
            "client_tool_allowlist": [] if no_tools else sorted(self._names),
        }
        await self._ws.send(json.dumps({"type": "input", "runtime": self._runtime,
                                        "payload": payload}))

    def _close_turn(self, reason):
        """Terminal stop: reset per-turn state and hand the turn back to the UI."""
        presence.nudge(energy=-0.02)
        had, tagged = self._turn_had_tool, self._tagged
        self._emitted.clear()
        self._turn_norm.clear()
        self._denied.clear()
        self._refused.clear()
        self._done.clear()
        self._answered.clear()
        self._turn_had_tool = False
        self._tagged = False
        self._last_status = ""
        if reason in ("end_turn", "stop") and not had and tagged and not self._tag_retry:
            self._spawn(self._tag_nudge(), "tag_retry")
            return
        self.bus.emit(E.ev(E.TURN, messages=[]))

    async def _tag_nudge(self):
        await asyncio.sleep(0.4)
        log("letta: tool_call tag in text but no call ran - nudging once")
        self._tag_retry = True
        await self._input("You wrote the tool call as text instead of calling it. "
                          "Do not repeat your answer - call the tool now.",
                          keep_task=True, is_retry=True)

    # -- pump ----------------------------------------------------------
    async def _pump(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            await self._dispatch(msg)

    async def _dispatch(self, msg):
        t = msg.get("type")
        d = msg.get("delta") if isinstance(msg.get("delta"), dict) else {}
        mt = d.get("message_type")

        if t == "runtime_start_response":
            if not msg.get("success"):
                self.bus.emit(E.ev(E.ERROR,
                                   text="letta start failed: %s" % msg.get("error")))
                self._runtime = None
            else:
                self._runtime = msg.get("runtime")
                agent = msg.get("agent") or {}
                log("letta agent tools: %s" % (agent.get("tools"),))
                aid = agent.get("id")
                if aid:
                    agents = dict(self.cfg.get("letta_agents") or {})
                    if agents.get("main") != aid:
                        agents["main"] = aid
                        self.cfg["letta_agents"] = agents
                        config.save()
            if self._started:
                self._started.set()
            return

        if t == "stream_delta":
            if mt == "loop_error":
                self.bus.emit(E.ev(E.ERROR, text=str(d.get("message") or "loop error")))
                return
            if mt == "stop_reason":
                reason = str(d.get("stop_reason") or "").lower()
                log("letta stop: %s" % reason)
                if reason in CONTINUE:
                    return
                self._close_turn(reason)
                return
            if mt == "assistant_message":
                self._emit_text(d)
                return
            if mt in ("tool_call", "tool_result"):
                log("letta %s: %s" % (mt, json.dumps(d)[:500]))
                body = _text_of(d.get("content"))
                if body:
                    self.bus.emit(E.ev(E.THINK, text=body[:300]))
                return
            log("letta delta %s: %s" % (mt, json.dumps(d)[:300]))
            return

        if t == "control_request":
            log("letta CONTROL: %s" % json.dumps(msg)[:900])
            self._spawn(self._approval(msg), "approval")
            return

        if t == "external_tool_call_request":
            log("letta TOOLREQ: %s" % json.dumps(msg)[:400])
            self._spawn(self._tool(msg), "tool")
            return

        if t == "update_loop_status":
            st = (msg.get("loop_status") or {}).get("status")
            if st:
                st = str(st).lower()
                if st not in NOISY and st != self._last_status:
                    self._last_status = st
                    self.bus.emit(E.ev(E.THINK, text=st))
            return

        log("letta unhandled %s: %s" % (t, json.dumps(msg)[:400]))

    def _emit_text(self, d):
        """Emit only the part of this message that is new for the message and the turn."""
        mid = d.get("id") or "?"
        raw = _text_of(d.get("content"))
        if "<tool_call" in raw or "<function_call" in raw:
            self._tagged = True
        full = _clean(raw)
        if not full.strip():
            return
        already = self._emitted.get(mid, "")
        if full == already:
            return
        new = full[len(already):] if (already and full.startswith(already)) else full
        self._emitted[mid] = full
        if not new.strip():
            return
        norm = _norm(new)
        if norm and any(norm == n or (len(norm) > 40 and norm in n)
                        for n in self._turn_norm):
            log("letta dropped repeated text (%d chars)" % len(norm))
            return
        if norm:
            self._turn_norm.append(norm)
        self.bus.emit(E.ev(E.DELTA, text=new))

    async def _send_decision(self, rid, allow, message):
        payload = {"kind": "approval_response", "request_id": rid,
                   "decision": {"behavior": "allow" if allow else "deny",
                                "message": message}}
        try:
            await self._ws.send(json.dumps({"type": "input",
                                            "runtime": self._runtime,
                                            "payload": payload}))
        except Exception as exc:
            log("letta approve send failed: %s" % exc)

    async def _deny_stop(self, name):
        log("letta deny ceiling for %s - stopping with no tools" % name)
        await self._abort()
        await asyncio.sleep(0.6)
        await self._input("%s was declined, so nothing was written. Answer in one "
                          "sentence." % name, no_tools=True, keep_task=True)

    async def _approval(self, msg):
        rid = msg.get("request_id") or (msg.get("request") or {}).get("request_id")
        if not rid or rid in self._answered:
            return
        self._answered.add(rid)
        req = msg.get("request") or {}
        call_id = req.get("tool_call_id") or ""
        name = req.get("tool_name") or req.get("tool") or "tool"
        args = req.get("input") or req.get("args") or {}
        sig = self._sig(name, args)

        if sig in self._refused:
            self._refused[sig] += 1
            log("letta re-deny %s (#%d)" % (name, self._refused[sig]))
            if call_id:
                self._denied.add(call_id)
            await self._send_decision(rid, False, self._refuse_message(sig))
            if self._refused[sig] >= MAX_REFUSE:
                self._spawn(self._deny_stop(name), "deny_stop")
            return

        pid = next(self._ids)
        slot = {"ev": threading.Event(), "ok": False}
        self.pending[pid] = slot
        self.bus.emit(E.ev(E.CONFIRM, id=pid, name=name, args=args))
        await asyncio.to_thread(slot["ev"].wait, 300)
        self.pending.pop(pid, None)

        if slot["ok"]:
            await self._send_decision(rid, True, "approved")
            log("letta approve -> %s allow" % rid)
        else:
            self._refused[sig] = 1
            if call_id:
                self._denied.add(call_id)
            await self._send_decision(rid, False, self._refuse_message(sig))
            log("letta approve -> %s deny" % rid)

    async def _tool(self, msg):
        call_id = msg.get("tool_call_id") or ""
        name = self._names.get(msg.get("tool_name"), msg.get("tool_name"))
        args = msg.get("input") or {}
        from ..tools import registry
        sig = self._sig(name, args)
        self._turn_had_tool = True

        if call_id and call_id in self._denied:
            log("letta skipped-by-approval %s" % name)
            self.bus.emit(E.ev(E.TOOL_RESULT, ok=False, text="skipped by the user"))
            await self._respond(msg, {"error": self._refuse_message(sig)}, True)
            return
        if sig in self._done:
            log("letta duplicate %s" % name)
            self.bus.emit(E.ev(E.TOOL_RESULT, ok=True, text="duplicate call - reused"))
            await self._respond(msg, {"note": "this exact call already ran in this turn - "
                                             "use the earlier result, do not repeat it",
                                      "previous": self._done[sig]}, False)
            return
        if self.cfg.get("confirm") and name in registry.CONFIRM and not call_id:
            pid = next(self._ids)
            slot = {"ev": threading.Event(), "ok": False}
            self.pending[pid] = slot
            self.bus.emit(E.ev(E.CONFIRM, id=pid, name=name, args=args))
            await asyncio.to_thread(slot["ev"].wait, 300)
            self.pending.pop(pid, None)
            if not slot["ok"]:
                self._refused[sig] = 1
                await self._respond(msg, {"error": self._refuse_message(sig)}, True)
                return
        self.bus.emit(E.ev(E.TOOL, name=name, args=args))
        tmo = int(self.cfg.get("tool_timeout") or 120)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(registry.run, name, args), tmo)
        except asyncio.TimeoutError:
            result = {"error": "tool timed out after %ds" % tmo}
        except Exception as exc:
            result = {"error": "%s: %s" % (type(exc).__name__, exc)}
        ok = "error" not in result
        if ok:
            self._done[sig] = result
        self.bus.emit(E.ev(E.TOOL_RESULT, ok=ok, text=json.dumps(result)[:600]))
        await self._respond(msg, result, not ok)

    async def _respond(self, msg, result, is_error):
        try:
            await self._ws.send(json.dumps({
                "type": "external_tool_call_response",
                "request_id": msg.get("request_id"),
                "result": {"is_error": bool(is_error),
                           "content": [{"type": "text",
                                        "text": json.dumps(result)[:6000]}]},
            }))
        except Exception as exc:
            log("letta tool response: %s" % exc)