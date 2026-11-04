"""Prove the Letta App Server protocol from Python before wiring it into MalO.

Registers one echo external tool, sends one message, prints every frame.
Run: python tools/letta_probe.py [unrestricted|standard|acceptEdits|strict]
"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

URL = "ws://127.0.0.1:4500"
LM = "http://127.0.0.1:1234/v1"
CWD = r"C:\Users\chugs\workspace"
IDLE = 240.0
CEILING = 900.0
MODE = (sys.argv[1] if len(sys.argv) > 1 else "unrestricted")

ECHO = {
    "name": "malo_echo",
    "label": "Echo",
    "description": "Echo a string back. Use it to prove the controller bridge works.",
    "parameters": {"type": "object",
                   "properties": {"text": {"type": "string"}},
                   "required": ["text"],
                   "additionalProperties": False},
}


def prewarm():
    try:
        models = json.loads(urllib.request.urlopen(LM + "/models", timeout=5).read())
        mid = (models.get("data") or [{}])[0].get("id") or ""
        if not mid:
            print("!! no model loaded in LM Studio")
            return False
        body = json.dumps({"model": mid, "max_tokens": 1,
                           "messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(LM + "/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        t = time.time()
        urllib.request.urlopen(req, timeout=600).read()
        print("prewarm ok in %.1fs" % (time.time() - t))
        return True
    except Exception as exc:
        print("!! prewarm failed:", exc)
        return False


async def main():
    print("mode:", MODE)
    prewarm()
    started = last = time.time()
    runtime = None
    ended = False
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "runtime_start",
            "request_id": "start-1",
            "create_agent": {"body": {"name": "MalO probe"}},
            "create_conversation": {"body": {}},
            "cwd": CWD,
            "mode": MODE,
            "external_tools": [{"tools": [ECHO]}],
        }))

        async for raw in ws:
            last = time.time()
            try:
                msg = json.loads(raw)
            except Exception:
                print("RAW", raw[:300])
                continue
            t = msg.get("type")
            d = msg.get("delta") if isinstance(msg.get("delta"), dict) else {}

            if t == "stream_delta":
                mt = d.get("message_type")
                if mt == "loop_error":
                    print("LOOP ERROR:", d.get("message"))
                elif mt == "stop_reason":
                    print("< stop_reason", d.get("stop_reason"))
                    if d.get("stop_reason") != "requires_approval":
                        ended = True
                elif mt in ("assistant_message", "tool_call", "tool_result"):
                    print("<", mt, json.dumps(d)[:500])
                elif d.get("content"):
                    print("<", mt, "content:", str(d.get("content"))[:200])
            elif t == "control_request":
                print("< CONTROL_REQUEST", json.dumps(msg)[:500])
                rid = msg.get("request_id") or (msg.get("request") or {}).get("request_id")
                await ws.send(json.dumps({
                    "type": "input",
                    "runtime": runtime,
                    "payload": {"kind": "approval_response", "request_id": rid,
                                "decision": {"behavior": "allow",
                                             "message": "probe auto-approve"}},
                }))
                print("  -> approved", rid)
            elif t == "external_tool_call_request":
                name = msg.get("tool_name")
                print("< tool_request", name, json.dumps(msg.get("input") or {})[:200])
                if name == "malo_echo":
                    text = str((msg.get("input") or {}).get("text") or "")
                    await ws.send(json.dumps({
                        "type": "external_tool_call_response",
                        "request_id": msg.get("request_id"),
                        "result": {"content": [{"type": "text",
                                                "text": "echo: " + text}]},
                    }))
                    print("  -> answered echo")
                else:
                    await ws.send(json.dumps({
                        "type": "external_tool_call_response",
                        "request_id": msg.get("request_id"),
                        "error": "unknown tool " + str(name),
                    }))
                    print("  -> refused unknown tool")
            elif t == "runtime_start_response":
                if not msg.get("success"):
                    print("start failed:", msg.get("error"))
                    return 1
                runtime = msg.get("runtime")
                agent = msg.get("agent") or {}
                print("agent model:", agent.get("model"), agent.get("model_settings"))
                await ws.send(json.dumps({
                    "type": "input",
                    "runtime": runtime,
                    "payload": {
                        "kind": "create_message",
                        "messages": [{
                            "role": "user",
                            "client_message_id": "probe-1",
                            "content": "Use the malo_echo tool with text 'bridge ok'. "
                                       "Then reply with exactly what the tool returned.",
                        }],
                    },
                }))
                print("  -> sent input")
            elif t == "update_device_status":
                ds = msg.get("device_status") or {}
                print("< device mode:", ds.get("current_permission_mode"),
                      "toolset:", ds.get("current_toolset"))
            elif t == "update_loop_status":
                print("< loop:", (msg.get("loop_status") or {}).get("status"))

            if ended and time.time() - last > 4:
                print("-- turn ended")
                return 0
            if time.time() - last > IDLE:
                print("-- idle %.0fs, aborting" % IDLE)
                if runtime:
                    await ws.send(json.dumps({"type": "abort_message",
                                              "request_id": "abort-1",
                                              "runtime": runtime}))
                await asyncio.sleep(2)
                return 0
            if time.time() - started > CEILING:
                print("-- ceiling")
                return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass