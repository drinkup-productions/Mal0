"""Console chat through the Letta client with MalO's real tools and jail.

Run from the repo root: python tools/letta_chat.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from malo.core import config, events as E, letta, perm


def main():
    config.load()
    config.CFG["perm"] = dict(perm.DEFAULTS)
    bus = E.Bus()

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
            a = input("\n  run %s %s ? [y/N] " % (ev.get("name"), ev.get("args")))
            chat.approve(ev.get("id"), a.strip().lower().startswith("y"))
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
            if not line.strip():
                break
            if not chat.send(line):
                print("not connected")
    finally:
        chat.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())