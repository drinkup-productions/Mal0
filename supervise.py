"""Watchdog launcher.

Runs `python -m malo`, promotes the tree to last-known-good after a healthy window,
and restores that tree if the app dies non-zero. Crash-loops stop after N restarts.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                    "MalOAvatar", "supervisor")
GOOD = os.path.join(BASE, "lastgood")
TMP = os.path.join(BASE, "staging")
LOG = os.path.join(BASE, "supervisor.log")
SKIP = {".git", "__pycache__", "bin", "build", "dist", ".venv", ".buildozer", "supervisor"}


def log(msg):
    os.makedirs(BASE, exist_ok=True)
    line = "%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line)
    sys.stdout.write(line)
    sys.stdout.flush()


def _ignore(_d, names):
    return [n for n in names if n in SKIP or n.endswith(".pyc")]


def copy_tree(src, dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=_ignore)


def promote():
    os.makedirs(BASE, exist_ok=True)
    copy_tree(ROOT, TMP)
    if os.path.isdir(GOOD):
        shutil.rmtree(GOOD)
    os.replace(TMP, GOOD)
    log("promoted current tree to last-known-good")


def restore():
    if not os.path.isdir(GOOD):
        log("no last-known-good to restore")
        return False
    for name in os.listdir(GOOD):
        s = os.path.join(GOOD, name)
        d = os.path.join(ROOT, name)
        if os.path.isdir(s):
            if os.path.isdir(d):
                shutil.rmtree(d)
            shutil.copytree(s, d, ignore=_ignore)
        else:
            shutil.copy2(s, d)
    log("restored last-known-good over the working tree")
    return True


def run_child(extra):
    return subprocess.Popen([sys.executable, "-m", "malo"] + extra, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser(prog="supervise")
    ap.add_argument("--restore", action="store_true", help="restore last-known-good and exit")
    ap.add_argument("--healthy", type=float, default=30.0,
                    help="seconds a run must survive to be promoted (default 30)")
    ap.add_argument("--max-restarts", type=int, default=3,
                    help="restarts allowed inside the window before giving up")
    ap.add_argument("--window", type=float, default=600.0, help="crash-loop window seconds")
    ap.add_argument("--no-promote", action="store_true")
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args()

    if a.restore:
        restore()
        return 0

    extra = [x for x in a.rest if x != "--"]
    os.makedirs(BASE, exist_ok=True)
    crashes = []
    log("supervisor start, healthy=%.0fs max_restarts=%d" % (a.healthy, a.max_restarts))

    while True:
        started = time.time()
        proc = run_child(extra)
        promoted = False
        while proc.poll() is None:
            if not promoted and time.time() - started >= a.healthy:
                if not a.no_promote:
                    try:
                        promote()
                    except Exception as exc:
                        log("promote failed: %s" % exc)
                promoted = True
            time.sleep(0.5)

        code = proc.returncode
        ran = time.time() - started
        if code == 0:
            log("clean exit after %.0fs" % ran)
            return 0

        log("child died code=%s after %.0fs" % (code, ran))
        now = time.time()
        crashes = [t for t in crashes if now - t < a.window] + [now]
        if len(crashes) > a.max_restarts:
            log("crash loop: %d deaths in %.0fs, stopping" % (len(crashes), a.window))
            return 1
        if ran < a.healthy:
            restore()
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())