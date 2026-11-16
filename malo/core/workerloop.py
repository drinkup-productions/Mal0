"""Claims broker jobs and runs them through the worker."""
import json
import threading
import time

from . import broker, config, events as E
from .log import log

POLL = 3.0


class WorkerLoop:
    def __init__(self, bus, cfg, loop):
        self.bus = bus
        self.cfg = cfg
        self.loop = loop
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="jobloop")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        conn = None
        while not self._stop.is_set():
            try:
                if conn is None:
                    conn = broker.connect()
                if not self.loop.alive():
                    self._stop.wait(POLL)
                    continue
                job = broker.claim(conn)
                if not job:
                    self._stop.wait(POLL)
                    continue
                if job["tier"] == "small" and not self.cfg.get("job_small_local"):
                    broker.finish(conn, job["id"],
                                  error="small tier not enabled on this machine")
                    continue
                self._run_job(conn, job)
            except Exception as exc:
                log("jobloop: %s: %s" % (type(exc).__name__, exc))
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                conn = None
                self._stop.wait(POLL * 2)
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    def _run_job(self, conn, job):
        cap = int(self.cfg.get("job_timeout") or 1800)
        log("job %s claimed: %s" % (job["id"], job["goal"][:80]))
        self.bus.emit(E.ev(E.THINK, text="job: " + job["goal"][:80]))
        text = ("[job %s] %s\n\nWork this to completion. Report the result in a "
                "short paragraph. If it cannot be done, say so in one line."
                % (job["id"], job["goal"]))
        done = threading.Event()
        box = {"ok": False, "stop": "", "text": ""}
        start = time.time()

        def watch():
            while not done.is_set() and time.time() - start < cap:
                if self._stop.is_set():
                    return
                time.sleep(1)
            if not done.is_set():
                box["stop"] = "timeout"

        threading.Thread(target=watch, daemon=True).start()
        self.loop.run([{"role": "user", "content": text}], "", max_steps=0)

        while not done.is_set() and time.time() - start < cap + 60:
            if not self.loop.alive():
                break
            time.sleep(1)
            if box["stop"] == "timeout":
                self.loop.release()
                break

        if box["stop"] == "timeout":
            broker.finish(conn, job["id"], error="timed out after %ds" % cap)
            log("job %s timed out" % job["id"])
        else:
            broker.finish(conn, job["id"],
                          result=self.loop.last_text or "completed with no report")
        self.bus.emit(E.ev(E.THINK, text="job done: " + job["id"]))