"""Letta App Server client.

Letta owns the turn loop, retries, compaction and memory. MalO owns the tools:
every tool is registered as a controller-owned external tool and dispatched
through registry.run, so the jail, the permission classes and the confirm gate
still apply.
"""
import asyncio
import itertools
import json
import threading
import time

from . import config, events as E, personas, presence, tasks
from .log import log

try:
    import websockets
except Exception:
    websockets = None

RECONNECT = 3.0


def _safe(name):
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in str(name))


def _tool_specs():
    """OpenAI-shaped registry specs -> Letta external tool definitions."""
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
    who = "\n\n".join(x for x in (p.get("self"), p.get("overlay")) if x)
    return pid, [
        {"label": "persona", "value": who or "You are MalO."},
        {"label": "human", "value": "The user owns this machine and runs you on it."},
    ]


def _system(cfg):
    return (
        "You are MalO, a program living on the user's Windows machine. You operate the "
        "desktop through tools: files, shell, windows, screenshots, mouse and keyboard. "
        "Look before you touch. Report what you did in a sentence. The newest user "
        "message always wins over older unfinished work. File tools are jailed to the "
        "workspace and the repo.\n\nWorkspace: %s\nSource repo: %s"
        % (cfg.get("workspace"), cfg.get("repo") or "(unset)")
    )


class Chat:
    def __init__(self, bus, cfg):
        self.bus = bus
        self.cfg = cfg
        self.pending = {}
        self._ids = itertools.count(1)
        self._names = {}
        self._loop = None
        self._ws = None
        self._runtime = None
        self._thread = None
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._seen = set()

    # -- lifecycle -----------------------------------------------------
    def start(self, timeout=25):
        if websockets is None:
            self.bus.emit(E.ev(E.ERROR, text="websockets not installed"))
            return False
        if self._thread and self._thread.is_alive():
            return self._ready.is_set()
        self._thread = threading.Thread(target=self._thread_main, daemon=True,
                                        name="letta")
        self._thread.start()
        return self._ready.wait(timeout)

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
            self._loop.close()

    async def _main(self):
        while not self._closed.is_set():
            try:
                async with websockets.connect(
                        self.cfg.get("letta_url") or "ws://127.0.0.1:4500",
                        max_size=None) as ws:
                    self._ws = ws
                    if not await self._start_runtime():
                        return
                    self._ready.set()
                    await self._pump(ws)
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

    # -- runtime -------------------------------------------------------
    async def _start_runtime(self):
        tools, self._names = _tool_specs()
        pid, blocks = _persona_blocks(self.cfg)
        agent_id = (self.cfg.get("letta_agents") or {}).get(pid)
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
            frame["create_agent"] = {"body": {"name": "MalO " + pid,
                                              "system": _system(self.cfg),
                                              "memory_blocks": blocks}}
            frame["create_conversation"] = {"body": {}}
        await self._ws.send(json.dumps(frame))
        # the response is handled in _pump; wait for the runtime
        for _ in range(400):
            if self._runtime:
                return True
            await asyncio.sleep(0.05)
        self.bus.emit(E.ev(E.ERROR, text="letta runtime_start timed out"))
        return False

    # -- turn ----------------------------------------------------------
    def send(self, text):
        if not self._loop or not self._ws or not self._runtime:
            return False
        asyncio.run_coroutine_threadsafe(self._input(text), self._loop)
        return True

    async def _input(self, text):
        tasks.begin(text)
        payload = {
            "kind": "create_message",
            "messages": [{"role": "user", "content": text,
                          "client_message_id": "m%d" % int(time.time() * 1000)}],
            "exclude_interactive_tools": True,
        }
        if not self.cfg.get("letta_builtin_tools"):
            payload["client_tool_allowlist"] = []
        await self._ws.send(json.dumps({"type": "input", "runtime": self._runtime,
                                        "payload": payload}))

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
                self.bus.emit(E.ev(E.ERROR, text="letta start failed: %s" % msg.get("error")))
                self._runtime = None
                return
            self._runtime = msg.get("runtime")
            agent = msg.get("agent") or {}
            aid = agent.get("id")
            if aid:
                pid = personas.active(self.cfg)
                agents = dict(self.cfg.get("letta_agents") or {})
                if agents.get(pid) != aid:
                    agents[pid] = aid
                    self.cfg["letta_agents"] = agents
                    config.save()
            return

        if t == "stream_delta":
            if mt == "loop_error":
                self.bus.emit(E.ev(E.ERROR, text=str(d.get("message") or "loop error")))
                return
            if mt == "stop_reason":
                if d.get("stop_reason") != "requires_approval":
                    self.bus.emit(E.ev(E.TURN, messages=[]))
                return
            if mt == "assistant_message":
                mid = d.get("id")
                if mid in self._seen:
                    return
                body = d.get("content") or ""
                if body:
                    self._seen.add(mid)
                    self.bus.emit(E.ev(E.DELTA, text=body))
                return
            if mt in ("tool_call", "tool_result", "status"):
                if d.get("content"):
                    self.bus.emit(E.ev(E.THINK, text=str(d["content"])[:300]))
            return

        if t == "control_request":
            await self._approval(msg)
            return

        if t == "external_tool_call_request":
            asyncio.create_task(self._tool(msg))
            return

        if t == "update_loop_status":
            st = (msg.get("loop_status") or {}).get("status")
            if st:
                self.bus.emit(E.ev(E.THINK, text=st.lower()))

    async def _approval(self, msg):
        rid = msg.get("request_id") or (msg.get("request") or {}).get("request_id")
        req = msg.get("request") or {}
        name = req.get("tool_name") or req.get("tool") or "tool"
        args = req.get("input") or req.get("args") or {}
        pid = next(self._ids)
        slot = {"ev": threading.Event(), "ok": False}
        self.pending[pid] = slot
        self.bus.emit(E.ev(E.CONFIRM, id=pid, name=name, args=args))
        await asyncio.to_thread(slot["ev"].wait, 300)
        self.pending.pop(pid, None)
        await self._ws.send(json.dumps({
            "type": "input",
            "runtime": self._runtime,
            "payload": {"kind": "approval_response", "request_id": rid,
                        "decision": {"behavior": "allow" if slot["ok"] else "deny",
                                     "message": "approved" if slot["ok"] else "skipped"}},
        }))

    async def _tool(self, msg):
        name = self._names.get(msg.get("tool_name"), msg.get("tool_name"))
        args = msg.get("input") or {}
        from ..tools import registry
        if self.cfg.get("confirm") and name in registry.CONFIRM:
            pid = next(self._ids)
            slot = {"ev": threading.Event(), "ok": False}
            self.pending[pid] = slot
            self.bus.emit(E.ev(E.CONFIRM, id=pid, name=name, args=args))
            await asyncio.to_thread(slot["ev"].wait, 300)
            self.pending.pop(pid, None)
            if not slot["ok"]:
                await self._respond(msg, {"note": "skipped by the user"}, True)
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