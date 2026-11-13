"""Entry point: argument parsing and wiring."""
import argparse
import os
import signal
import sys
import threading

from .core import log as _log, personas, provider, runtime, skills
from .tools import mcp


def main():
    argv = sys.argv[1:]
    if "--mcp-test" in argv:
        return mcp_test()

    ap = argparse.ArgumentParser(prog="malo")
    ap.add_argument("--server", action="store_true", help="headless, no window")
    ap.add_argument("--web", action="store_true", help="serve the web front end")
    ap.add_argument("--no-tray", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--webview", action="store_true")
    ap.add_argument("--pair", nargs="?", const="cli",
                    help="mint a broker device token and exit")
    ap.add_argument("--broker", action="store_true", help="run the job broker")
    args = ap.parse_args()

    rt = runtime.Runtime()

    if args.pair:
        from .core import broker
        return broker.pair(args.pair)

    if args.selftest:
        return selftest(rt)

    if not rt.cfg.get("mcp_via_sdk"):
        threading.Thread(target=mcp.start_all, daemon=True).start()
    if args.broker:
        from .core import broker
        threading.Thread(target=_run_broker, args=(broker,), daemon=True).start()
    personas.save()
    skills.load_all()
    _log.log("start platform=%s persona=%s broker=%s"
             % (rt.platform.name, personas.active(rt.cfg), bool(args.broker)))

    if args.server:
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        stop.wait()
        mcp.stop_all()
        rt.audio.stop_all()
        return

    if args.web:
        from .web.server import serve
        return serve(rt, args.port)

    if rt.platform.name == "android":
        from .ui.kivy.app import ChatApp
        ChatApp(rt).run()
    else:
        from .ui.tk.app import App
        App(rt, want_tray=not args.no_tray).run()


def _run_broker(broker):
    try:
        broker.serve()
    except OSError as exc:
        _log.log("broker failed: %s" % exc)
        print("broker failed: %s" % exc)


def selftest(rt):
    print("platform :", rt.platform.name)
    print("data     :", rt.paths.root)
    print("audio    :", rt.audio.backend)
    print("workspace:", rt.cfg.get("workspace"))
    print("base url :", rt.cfg.get("base_url"))
    print("personas :", ", ".join(personas.PERSONAS))
    print("skills   :", len(skills.specs()))
    print("models   :", provider.build(rt.cfg).models() or "(none)")
    print("mcp      :", mcp.status())
    for d in (rt.paths.output, rt.paths.sfx_dir, rt.paths.personas_dir):
        print("exists   :", d, os.path.isdir(d))


def mcp_test():
    runtime.Runtime()
    mcp.start_all()
    for row in mcp.status():
        if row["ready"]:
            state = "ready"
        elif row["error"]:
            state = "FAILED: " + row["error"]
        else:
            state = "off"
        print("%-12s tools=%-3d %s" % (row["name"], row["tools"], state))
        with mcp.LOCK:
            c = mcp.SERVERS.get(row["name"])
        for t in (c.tools if c else []):
            print("    -", t.get("name"))
    mcp.stop_all()


if __name__ == "__main__":
    main()