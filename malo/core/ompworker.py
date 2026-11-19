"""OMP RPC backend for MalO (config "backend": "omp").

Drop-in replacement for :class:`malo.core.workerproc.Worker`: identical public
surface (start / send / perm / approve / tool_result / abort / busy / restart /
alive / close) and the same internal ``on_event`` vocabulary, so Loop,
workerloop and every UI run unchanged. Only the spawned child changes:

    legacy:  python -m malo.worker   -> Letta (core/bridge.py or bridge.mjs)
    omp:     omp --mode rpc-ui       -> this adapter speaks OMP's JSONL RPC

Protocol reference (OMP "rpc" mode, protocol v1; the ready frame reports the
supported versions and we stay on v1 — no negotiate_protocol needed):

  stdin (commands we send)                stdout (frames we receive)
  ------------------------------------    -------------------------------------------------
  {id,type:"prompt",message}              ready                          -> "ready" + setup()
  {type:"abort"}                          response                       -> correlate by id
  {id,type:"get_state"}                   agent_start/turn_*/...         -> mostly ignored
  {id,type:"switch_session",sessionPath}  message_start / message_update -> "text"/"think"
  {id,type:"set_host_tools",tools}        tool_execution_end             -> "result" (builtins)
  {type:"host_tool_result",...}           host_tool_call / _cancel       -> "tool" / log
  {type:"extension_ui_response",...}      extension_ui_request           -> "approval"/log
                                           queue_update                   -> "queue"
                                           prompt_result                  -> "done" (turn end)
                                           agent_end(isTerminal)          -> "done" (bg runs)

Frame notes (verified against a live probe + OMP's rpc.md):

- message_start/update carry ``messageId`` ("msg-N") plus the FULL partial
  message, not just the delta. Loop._event diffs cumulative buffers per id,
  so we replay the whole text/thinking each frame; identical re-sends diff to
  "" and are free.
- A turn ends with prompt_result{id,status} for our prompt id: completed /
  aborted / error (error carries {message}). Pre-agent failures also emit a
  response{success:false}, but their prompt_result still follows, so "done"
  is only ever emitted from prompt_result.
- Runs OMP continues without one of our prompts (goal-mode continuations)
  end with agent_end{isTerminal:true}; we present a synthetic "done" when we
  saw assistant traffic since the last turn and nothing else is in flight.
- Closing stdin IS clean shutdown for OMP (pending requests rejected, session
  disposed, exit 0), so close() just closes the pipe instead of sending stop.

Session continuity across respawns: after ready we get_state and persist
data.sessionFile into cfg["omp_session"]; on every later spawn (crash
recovery or a permission respawn) switch_session{sessionPath} restores the
conversation — the OMP equivalent of Letta keeping agent/conversation state
server-side. A failed resume clears the pointer and continues fresh instead
of wedging.

Permission mapping: Loop.run() sends "standard" while cfg.confirm is on,
"unrestricted" when off. Approval mode is a per-process setting in OMP (no
mid-session RPC command), so perm() respawns synchronously when the mapped
flag changes — safe because run() calls perm() right before send():

    standard     -> --approval-mode write   (read+write auto, exec prompts)
    unrestricted -> --approval-mode yolo    (nothing prompts)

Approval prompts arrive as extension_ui_request(method:"select") with the
same choices as the TUI (Approve / Approve <tool> for this session / Deny).
We surface them as internal "approval" events; approve() answers by picking
the first non-deny option (ok=True) or the deny option (ok=False).

Host tools: after ready we read data.dumpTools from get_state and mount only
the registry specs whose names do NOT collide with OMP builtins via
set_host_tools (same {"name","label","description","parameters"} shape the
letta bridge received as --tools-file; e.g. "bash"/"read"/"write" stay
OMP's own, while screen/uia/vision/memory and friends get mounted). When OMP
calls one of them it emits host_tool_call -> internal "tool"; Loop._event
runs it via registry.run exactly as before (thread + timeout + 24k JSON cap)
and answers with worker.tool_result(), which becomes a host_tool_result
frame. Errors use the top-level isError flag so OMP surfaces them as tool
errors to the model.

UI methods beyond binary confirms: select/confirm become approval events;
input/editor are answered cancelled (fail closed); ask is answered cancelled
too, which makes OMP auto-answer every question with its recommended option
(the least-surprise default for MalO's binary-only GUI). Presentation
methods (notify/setStatus/setWidget/setTitle/open_url) need no reply.
"""
import os
import threading

from . import config
from .log import log
from .workerproc import Worker


def _perm_flag(mode):
    """Map MalO permission names to OMP --approval-mode values."""
    return "yolo" if (mode or "") == "unrestricted" else "write"


class OmpWorker(Worker):
    def __init__(self, cfg, on_event):
        super().__init__(cfg, on_event)
        self._seq = 0            # request id counter ("omp-N")
        self._open_prompts = {}  # prompt id -> True while a turn is in flight
        self._last_text = ""     # cumulative text of the newest assistant message
        self._bg_seen = False    # assistant traffic outside any tracked prompt
        self._ui_method = {}     # extension_ui_request id -> method
        self._ui_opts = {}       # extension_ui_request id -> option labels
        self._unseen = set()     # frame types already logged by _frame
        self._respawn_evt = threading.Event()  # set on every ready frame
        # Loop.run() passes perm() before every send; remember the flag we want
        # so a respawn (crash recovery or perm change) picks it up in _argv().
        self._want_perm = "standard" if cfg.get("confirm") else "unrestricted"
        self._active_perm = None  # approval flag actually used by the live process

    # -- spawning ---------------------------------------------------------
    def _sync_persona(self):
        """Give the OMP session MalO's identity.

        Letta mode passed ``--persona-file <repo>/persona.md`` and the bridge set
        it as the agent system prompt. RPC mode has no equivalent command, so we
        copy the same text into the project context file OMP auto-loads for every
        spawn in its cwd: ``<workspace>/.omp/AGENTS.md`` (searched from cwd up to
        the repo root). Written before Popen, only when content changed. A write
        failure never blocks spawning — the agent just starts without persona.
        """
        src = self.cfg.get("persona_file") or os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "persona.md"))
        try:
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:
            log("omp persona unreadable (%s): %s" % (src, exc))
            return
        d = os.path.join(self.cfg.get("workspace") or ".", ".omp")
        dst = os.path.join(d, "AGENTS.md")
        try:
            with open(dst, encoding="utf-8") as fh:
                if fh.read() == text.rstrip() + "\n":
                    return  # already in place (respawns are cheap)
        except FileNotFoundError:
            pass
        try:
            os.makedirs(d, exist_ok=True)
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(text.rstrip() + "\n")
            log("omp persona -> %s" % dst)
        except Exception as exc:
            log("omp persona write failed (%s): %s" % (dst, exc))

    def _argv(self):
        self._sync_persona()
        binpath = self.cfg.get("omp_bin") or "omp"
        argv = [binpath, "--mode", "rpc-ui",
                "--cwd", self.cfg.get("workspace") or os.getcwd(),
                "--approval-mode", _perm_flag(self._want_perm)]
        model = self.cfg.get("omp_model") or ""
        if model:
            argv += ["--model", str(model)]
        extra = self.cfg.get("omp_args") or []  # free-form escape hatch (--provider ...)
        if isinstance(extra, str):
            extra = extra.split()
        return argv + [str(a) for a in extra]

    def _remember(self, msg):
        # Base persists letta agent/conversation ids from the ready frame and
        # consumes rebuild_agent; OMP has no such concepts — its session state
        # lives in cfg["omp_session"], handled by _on_response instead.
        pass

    # -- stdout frames ------------------------------------------------------
    def _frame(self, msg):
        t = msg.get("type")
        if t == "ready":
            self._tries = 0
            # fresh process: forget in-flight turns/dialogs from any old one
            self._open_prompts = {}
            self._ui_method = {}
            self._ui_opts = {}
            self._bg_seen = False
            self._last_text = ""
            self._pending.clear()
            # record which approval flag this process actually runs with, and
            # wake any perm() call that is waiting for a respawn to become ready
            self._active_perm = _perm_flag(self._want_perm)
            self._respawn_evt.set()
            # setup BEFORE the ready event: anything Loop sends right after
            # "ready" must be queued behind switch_session/get_state, and OMP
            # processes commands in receive order.
            self._setup()
            self._ready.set()
            self.on_event("ready", msg)
        elif t == "response":
            self._on_response(msg)
        elif t in ("message_start", "message_update"):
            self._on_message(msg)
        elif t == "tool_execution_end":
            self._on_tool_event(msg)
        elif t == "host_tool_call":
            # Loop._event("tool") runs registry.run(name, input) and answers
            # via worker.tool_result(id, ...) -> host_tool_result below.
            self.on_event("tool", {"id": msg.get("id"),
                                   "name": msg.get("toolName") or "",
                                   "input": msg.get("arguments")})
        elif t == "host_tool_cancel":
            # Loop's worker thread may still deliver a result; OMP drops it.
            log("omp host tool cancelled: %s" % msg.get("targetId"))
        elif t == "extension_ui_request":
            self._on_ui(msg)
        elif t == "queue_update":
            n = len(msg.get("steering") or []) + len(msg.get("followUp") or [])
            self.on_event("queue", {"n": n})
        elif t == "prompt_result":
            self._on_prompt_result(msg)
        elif t == "agent_end" and msg.get("isTerminal"):
            self._on_bg_done()
        elif t not in (None, ""):
            # turn_*, command_output, subagent_*, advisor noise, session_settled...
            # need no UI action; log each unknown type once for diagnostics.
            if t not in self._unseen:
                self._unseen.add(t)
                log("omp frame (no action): %s" % t)

    def _setup(self):
        """Post-ready handshake: resume the saved session, then get_state.

        set_host_tools is sent from _on_response once get_state returns its
        dumpTools list, so colliding names can be filtered out first."""
        sf = self.cfg.get("omp_session") or ""
        if sf and os.path.exists(sf):
            # restore conversation; failure handled in _on_response (fresh start)
            self._write({"id": "sw", "type": "switch_session", "sessionPath": sf})
        # sequential after switch_session, so it reports the resumed session
        self._write({"id": "gs", "type": "get_state"})

    def _on_response(self, msg):
        cmd = msg.get("command") or ""
        if not msg.get("success"):
            err = str(msg.get("error") or "")
            log("omp %s failed: %s" % (cmd, err))
            if cmd == "switch_session":
                # stale/broken pointer (file moved, model gone): go fresh
                self.cfg["omp_session"] = ""
                config.save()
                self.on_event("log", {"text": "omp resume failed (%s), new session"
                                      % err[:200]})
            elif cmd == "set_host_tools":
                # usually a name collision; keep going without host tools
                self.on_event("error", {"text": "host tools not mounted: %s"
                                        % err[:200]})
            return
        if cmd == "get_state":
            data = msg.get("data") or {}
            sf = data.get("sessionFile")
            if sf and sf != self.cfg.get("omp_session"):
                self.cfg["omp_session"] = sf
                config.save()
            # mount host tools, skipping names OMP already owns (dumpTools)
            builtins = {t.get("name") for t in (data.get("dumpTools") or [])
                        if isinstance(t, dict)}
            all_specs = self._host_specs()
            specs = [s for s in all_specs if s["name"] not in builtins]
            skipped = len(all_specs) - len(specs)
            if skipped:
                log("omp host tools: skipped %d colliding with OMP builtins"
                    % skipped)
            if specs:
                self._write({"id": "ht", "type": "set_host_tools",
                             "tools": specs})

    def _on_message(self, msg):
        m = msg.get("message") or {}
        # user messages are echoed back (our own prompt) — ignore those
        if m.get("role") != "assistant":
            return
        mid = str(msg.get("messageId") or "?")
        parts = m.get("content") or []
        text = "".join(c.get("text", "") for c in parts
                       if c.get("type") == "text")
        think = "".join(c.get("thinking", "") for c in parts
                        if c.get("type") == "thinking")
        # OMP sends deltas; Loop._event diffs cumulative buffers per id, so we
        # replay the full partial content (carried whole on every frame).
        if text:
            self._last_text = text
            if not self._open_prompts:
                self._bg_seen = True
            self.on_event("text", {"id": mid, "text": text})
        if think:
            # distinct id: Loop keeps one delta table per message id
            self.on_event("think", {"id": mid + "~t", "text": think})

    def _on_tool_event(self, msg):
        # GUI feedback for OMP's built-in tools (same event the letta path
        # used); fields parsed defensively across OMP versions.
        name = msg.get("name") or msg.get("toolName") or "tool"
        err = bool(msg.get("isError")) or bool(msg.get("error"))
        self.on_event("result", {"ok": not err,
                                 "text": ("%s: %s" % (name, "failed" if err else "done"))[:200]})

    def _on_ui(self, msg):
        method = msg.get("method") or ""
        ident = str(msg.get("id") or "")
        # presentation + housekeeping methods are fire-and-forget: no reply
        if method in ("notify", "setStatus", "setWidget", "setTitle",
                      "open_url", "cancel"):
            log("omp ui %s" % (method or "?"))
            self._ui_method.pop(ident, None)
            self._ui_opts.pop(ident, None)
            return
        if method in ("select", "confirm"):
            opts = [str(o) for o in (msg.get("options") or [])]
            self._ui_method[ident] = method
            self._ui_opts[ident] = opts
            # OMP gates host-tool calls behind these selects even in write mode
            # ("Allow tool: write / Path: xd://<name>") — this is MalO's confirm
            # UX for custom tools; approve() picks the option label to answer.
            log("omp approval prompt: %s" % (msg.get("title") or method)[:200])
            # internal "approval" -> Loop emits CONFIRM; GUI answers via approve()
            self.on_event("approval", {"id": ident,
                                       "name": msg.get("title") or method,
                                       "input": {"message": msg.get("message") or "",
                                                 "options": opts}})
            return
        # input / editor / ask: MalO's GUI only renders binary confirms. Fail
        # closed; for `ask` a cancel reply makes OMP answer every question with
        # its recommended (else first) option — the least-surprise default.
        log("omp ui %s unsupported by GUI, answering default" % method)
        self._write({"type": "extension_ui_response", "id": ident,
                     "cancelled": True})

    def _on_prompt_result(self, msg):
        rid = str(msg.get("id") or "")
        if rid not in self._open_prompts:
            return  # settled before/without our tracking (pre-admit abort etc.)
        del self._open_prompts[rid]
        self._pending.discard(rid)
        status = msg.get("status") or "completed"
        m = {"ok": status in ("completed", "aborted"), "text": self._last_text}
        if not m["ok"]:
            err = msg.get("error") or {}
            code = str(err.get("message") or msg.get("code") or status)
            m["code"] = code.splitlines()[0][:300]
        elif status == "aborted":
            m["stop"] = "aborted"
        # present the turn only when nothing of ours is still in flight; a
        # queued steering prompt settles earlier without closing the UI turn
        if not self._open_prompts:
            self.on_event("done", m)

    def _on_bg_done(self):
        # goal-mode / async continuations run with no prompt behind them
        if self._open_prompts or not self._bg_seen:
            return
        self._bg_seen = False
        self.on_event("done", {"ok": True, "text": self._last_text})

    # -- commands (same surface as Worker) -----------------------------------
    def _next_id(self):
        self._seq += 1
        return "omp%d" % self._seq

    def send(self, text):
        rid = self._next_id()
        if not self._write({"id": rid, "type": "prompt", "message": text}):
            return False
        # OMP itself queues a prompt behind an active run (steer/follow-up);
        # we track every in-flight turn and present done on the last one.
        self._open_prompts[rid] = True
        self._pending.add(rid)
        self._last_text = ""
        return True

    def perm(self, mode):
        flag = _perm_flag(mode or "standard")
        self._want_perm = (mode or "standard")
        if not self._ready.is_set():
            # startup still in flight: just record; the live spawn matches it
            return True
        if self._active_perm == flag:
            return True
        # approval mode is per-process in OMP -> synchronous respawn. Loop.run()
        # calls this before send(), so the turn simply waits for the restart.
        log("omp perm %s -> restarting worker" % (mode or "standard"))
        proc = self.proc
        if not proc or proc.poll() is not None:
            # no live process to replace; whatever spawns next (supervisor
            # backoff or a fresh start) reads the new flag in _argv()
            return True
        # _intentional tells the base reader this exit is planned, so it
        # respawns immediately with zero delay and emits no "worker exited"
        # error events; we then block until the new process reports ready.
        self._respawn_evt.clear()
        self._intentional = True
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return bool(self._respawn_evt.wait(60.0)) and self.alive()

    def approve(self, ident, ok):
        self._pending.discard(ident)
        method = self._ui_method.get(ident)
        opts = self._ui_opts.pop(ident, None) or []
        self._ui_method.pop(ident, None)
        if method == "select":
            denyish = ("deny", "reject", "cancel")
            label = ""
            if ok:
                for o in opts:  # choices arrive approve-first per OMP docs
                    if not any(w in o.lower() for w in denyish):
                        label = o
                        break
            else:
                for o in reversed(opts):
                    if any(w in o.lower() for w in denyish):
                        label = o
                        break
            payload = {"type": "extension_ui_response", "id": ident,
                       "value": label or (opts[0] if opts and ok else "")}
        elif method == "confirm":
            payload = {"type": "extension_ui_response", "id": ident,
                       "confirmed": bool(ok)}
        else:
            # unknown/stale dialog: fail closed
            payload = {"type": "extension_ui_response", "id": ident,
                       "cancelled": True}
        return self._write(payload)

    def tool_result(self, ident, text, error=False):
        payload = {"type": "host_tool_result", "id": str(ident),
                   "result": {"content": [{"type": "text", "text": text}]}}
        if error:
            # top-level flag makes OMP surface the text as a tool error
            payload["isError"] = True
        return self._write(payload)

    def abort(self):
        return self._write({"type": "abort"})

    def close(self):
        # closing stdin is OMP's clean shutdown: pending requests are rejected,
        # accepted commands drain, the session is disposed and it exits 0
        self._stopping = True
        proc = self.proc
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
