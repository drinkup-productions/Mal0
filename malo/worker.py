"""Worker process: owns the bridge, the session and the tools.

The host can kill and restart this freely. Nothing here owns a window.
"""
import argparse
import json
import os
import sys
import threading

from .core import config
from .core.bridge import Bridge


def _out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser()
    for flag in ("url", "cwd", "perm", "model", "mcp-file", "tools-file",
                 "persona-file", "agent", "conv"):
        ap.add_argument("--" + flag, default="")
    args = ap.parse_args(argv)

    cfg = {
        "letta_url": args.url or "ws://127.0.0.1:4500",
        "workspace": args.cwd or os.getcwd(),
        "permission_mode": args.perm or "standard",
        "letta_model": args.model,
        "mcp_file": args.mcp_file,
        "persona_file": args.persona_file,
        "letta_agent": args.agent,
        "letta_conversation": args.conv,
        "tool_timeout": int(config.get("tool_timeout") or 120),
    }

    bridge = Bridge(cfg, _out)
    if not bridge.start():
        _out({"ev": "error", "text": "worker bridge failed: %s" % bridge.error})
        _out({"ev": "dead", "text": bridge.error})
        return 1

    stopping = threading.Event()

    def pump():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            cmd = msg.get("cmd")
            if cmd == "send":
                bridge.send(msg.get("text") or "")
            elif cmd == "approve":
                bridge.approve(msg.get("id"), bool(msg.get("ok")))
            elif cmd == "tool_result":
                bridge.tool_result(msg.get("id"), msg.get("text") or "",
                                   bool(msg.get("error")))
            elif cmd == "perm":
                bridge.perm(msg.get("mode") or "standard")
            elif cmd == "abort":
                bridge.abort()
            elif cmd == "stop":
                stopping.set()
                break
        stopping.set()

    threading.Thread(target=pump, daemon=True, name="worker-in").start()

    while not stopping.is_set():
        stopping.wait(0.5)

    bridge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())