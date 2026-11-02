#!/usr/bin/env python3
"""Headless eval harness.

  python tests/evals/run.py --model qwen3-30b-a3b
  python tests/evals/run.py --models qwen3-30b-a3b,gpt-oss-20b --repeat 3
  python tests/evals/run.py --model qwen3-30b-a3b --tag core --json out.json
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from malo import platform as plat
from malo.core import config, engine, events as E, personas, memory
from malo.tools import mcp

HERE = os.path.dirname(os.path.abspath(__file__))
TASKS = os.path.join(HERE, "tasks")


def _numbered(spec):
    n = int(spec.get("count", 100))
    return "".join("%d line-%d\n" % (i, i) for i in range(1, n + 1))


GENERATORS = {"numbered_lines": _numbered}


def load_tasks(only=None, tag=None):
    out = []
    for name in sorted(os.listdir(TASKS)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(TASKS, name), encoding="utf-8") as fh:
            t = json.load(fh)
        if only and only.lower() not in t["id"].lower():
            continue
        if tag and tag not in (t.get("tag") or []):
            continue
        out.append(t)
    return out


def write_setup(ws, items):
    for it in items or []:
        p = os.path.join(ws, it["path"])
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)
        text = it["content"] if "content" in it else GENERATORS[it["kind"]](it)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)


def _read(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def check(ws, spec, res):
    k = spec["kind"]
    p = os.path.join(ws, spec["path"]) if spec.get("path") else None
    if k == "file_exists":
        return os.path.isfile(p)
    if k == "file_absent":
        return not os.path.exists(p)
    if k == "file_contains":
        return os.path.isfile(p) and spec["value"] in _read(p)
    if k == "file_matches":
        return os.path.isfile(p) and re.search(spec["pattern"], _read(p), re.S | re.I) is not None
    if k == "file_equals":
        return os.path.isfile(p) and _read(p) == spec["value"]
    if k == "response_contains":
        return spec["value"].lower() in res["text"].lower()
    if k == "response_matches":
        return re.search(spec["pattern"], res["text"], re.S | re.I) is not None
    if k == "tool_called":
        return spec["name"] in res["tools"]
    if k == "tool_not_called":
        return spec["name"] not in res["tools"]
    if k == "no_error_events":
        return not res["errors"]
    return False


def run_task(task, model):
    tmp = tempfile.mkdtemp(prefix="malo-eval-")
    os.environ["MALO_DATA"] = tmp
    config.reset()
    cfg = config.load()
    ws = os.path.join(tmp, "ws")
    os.makedirs(ws, exist_ok=True)
    cfg.update({"workspace": ws, "model": model, "temperature": 0.0,
                "confirm": bool(task.get("confirm")),
                "persona": task.get("persona", "malo")})
    personas.load()
    write_setup(ws, task.get("setup"))
    write_setup(ws, task.get("setup_generated"))
    
    for fact in task.get("memory") or []:
        memory.add(fact, "user", 0.9, source="eval")

    bus = E.Bus()
    eng = engine.Engine(bus, cfg)
    res = {"text": "", "tools": [], "errors": []}
    done = threading.Event()

    def handle(ev):
        t = ev.get("type")
        if t == E.DELTA:
            res["text"] += ev["text"]
        elif t == E.TOOL:
            res["tools"].append(ev["name"])
        elif t == E.CONFIRM:
            eng.approve(ev["id"], True)
        elif t == E.ERROR:
            res["errors"].append(ev["text"])
        elif t == E.TURN:
            done.set()

    started = time.time()
    msgs = [{"role": "user", "content": task["prompt"]}]
    threading.Thread(target=eng.run,
                     args=(msgs, model, plat.current().name, int(task.get("max_steps", 16))),
                     daemon=True).start()
    while not done.is_set() and time.time() - started < float(task.get("timeout", 120)):
        bus.drain(handle)
        time.sleep(0.02)
    bus.drain(handle)
    if not done.is_set():
        eng.release()
        res["errors"].append("timeout")

    fails = []
    for spec in task.get("checks") or []:
        try:
            if not check(ws, spec, res):
                fails.append(spec)
        except Exception as exc:
            fails.append({"kind": spec.get("kind"), "error": str(exc)})
    return tmp, fails, res, time.time() - started


def run_suite(model, tasks, args):
    rows = []
    for task in tasks:
        if "mcp" in (task.get("requires") or []) and not args.with_mcp:
            rows.append({"id": task["id"], "model": model, "run": 0,
                         "status": "skipped", "secs": 0.0, "tools": [], "fails": []})
            continue
        for n in range(args.repeat):
            tmp, fails, res, secs = run_task(task, model)
            rows.append({"id": task["id"], "model": model, "run": n + 1,
                         "status": "pass" if not fails else "fail",
                         "secs": round(secs, 1), "tools": res["tools"], "fails": fails})
            if not args.keep:
                shutil.rmtree(tmp, ignore_errors=True)
    return rows


def report(rows, args):
    width = max([len(r["id"]) for r in rows] + [8]) + 2
    print("%-*s %-10s %-4s %-7s %-5s %s" % (width, "task", "run", "res", "secs", "tools", "why"))
    for r in rows:
        why = "" if r["status"] == "pass" else "; ".join(
            f.get("kind", "?") for f in r["fails"])[:60]
        print("%-*s %-10d %-7s %-5s %-5d %s"
              % (width, r["id"], r["run"], r["status"], r["secs"], len(r["tools"]), why))

    total = [r for r in rows if r["status"] != "skipped"]
    ok = [r for r in total if r["status"] == "pass"]
    print("\n%d/%d pass" % (len(ok), len(total)), end="")
    if total:
        print(" (%.1f%%)" % (100.0 * len(ok) / len(total)))
    else:
        print()
    return 0 if len(ok) == len(total) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--models")
    ap.add_argument("--only")
    ap.add_argument("--tag")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--with-mcp", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args()

    models = [m for m in (args.models or args.model or "").split(",") if m]
    if not models:
        ap.error("--model or --models required")

    tasks = load_tasks(args.only, args.tag)
    if not tasks:
        print("no tasks matched")
        return 1

    if args.with_mcp:
        mcp.start_all()
        time.sleep(2)

    rows = []
    try:
        for m in models:
            rows += run_suite(m, tasks, args)
    finally:
        if args.with_mcp:
            mcp.stop_all()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)

    return report(rows, args)


if __name__ == "__main__":
    sys.exit(main())