"""Console chat through the Letta client with MalO's real tools and jail.

Run from the repo root: python tools/letta_chat.py [--ask]
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from malo.core import config, events as E, letta, perm
from malo.core import log as _log

ASK = "--ask" in sys.argv


def main():
    root = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                        "MalOAvatar")
    os.makedirs(root, exist_ok=True)
    _log.set_path(os.path.join(root, "malo.log"))
    config.load()
    config.CFG["perm"] = dict(perm.DEFAULTS)
    config.CFG["workspace"] = os.path.expanduser("~\\workspace")
    config.CFG["repo"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(config.CFG["workspace"], exist_ok=True)
    print("workspace:", config.CFG["workspace"])
    print("confirms:", "ask" if ASK else "auto-approve")
    bus = E.Bus()
    chat = None
    waiting = {"id": None, "name": "", "args": None}

    def handle(ev):
        t = ev.get("type")
        if t == E.DELTA:
            print(ev.get("text"), end="", flush=True)
        elif t == E.TOOL:
            print("\n> %s %s" % (ev.get("name"), ev.get("args")))
        elif t == E.TOOL_RESULT:
            print("  %s" % ev.get("text"))
        elif t == E.THINK:
            print("[%s]" % ev.get("text"))
        elif t == E.ERROR:
            print("\n!! %s" % ev.get("text"))
        elif t == E.CONFIRM:
            if ASK:
                waiting["id"], waiting["name"], waiting["args"] = (
                    ev.get("id"), ev.get("name"), ev.get("args"))
                print("\n  CONFIRM %s %s - type y or n" % (ev.get("name"), ev.get("args")))
            else:
                print("\n  auto-approve %s" % ev.get("name"))
                chat.approve(ev.get("id"), True)
        elif t == E.TURN:
            print()

    def drain():
        while True:
            bus.drain(handle)
            time.sleep(0.05)

    threading.Thread(target=drain, daemon=True).start()
    chat = letta.Chat(bus, config.CFG)
    if not chat.start():
        print("could not reach letta at", config.CFG.get("letta_url"))
        return 1
    print("connected. blank line quits.")
    try:
        while True:
            try:
                line = input("\nyou> ")
            except EOFError:
                break
            if waiting["id"] is not None:
                ok = line.strip().lower().startswith("y")
                chat.approve(waiting["id"], ok)
                waiting["id"] = None
                print("  %s" % ("approved" if ok else "skipped"))
                continue
            if not line.strip():
                break
            if not chat.send(line):
                print("not connected")
    finally:
        chat.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())