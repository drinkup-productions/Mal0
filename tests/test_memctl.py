"""Memory blocks against a temp memfs."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from malo.core import config, memctl

TMP = None


def setUpModule():
    global TMP
    TMP = tempfile.mkdtemp(prefix="malo-memctl-")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Mem(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)
        self._env = os.environ.get("LETTA_LOCAL_BACKEND_DIR")
        os.environ["LETTA_LOCAL_BACKEND_DIR"] = self.d
        config.CFG.clear()
        config.CFG.update({"letta_agent": "agent-test",
                           "memory_budget_tokens": 800})
        self._total = mock.patch.object(
            memctl, "total", lambda: len(memctl.read("notes")) // 4)
        self._total.start()

    def tearDown(self):
        self._total.stop()
        if self._env is None:
            os.environ.pop("LETTA_LOCAL_BACKEND_DIR", None)
        else:
            os.environ["LETTA_LOCAL_BACKEND_DIR"] = self._env
        shutil.rmtree(self.d, ignore_errors=True)

    def test_append_and_read(self):
        memctl.append("notes", "alpha")
        self.assertIn("alpha", memctl.read("notes"))

    def test_append_keeps_existing(self):
        memctl.append("notes", "alpha")
        memctl.append("notes", "beta")
        body = memctl.read("notes")
        self.assertIn("alpha", body)
        self.assertIn("beta", body)

    def test_unknown_label(self):
        with self.assertRaises(ValueError):
            memctl.read("nope")

    def test_prune_drops_oldest(self):
        for i in range(40):
            memctl.append("notes", "line %02d %s" % (i, "x" * 40))
        config.CFG["memory_budget_tokens"] = 60
        out = memctl.prune()
        self.assertGreater(out["pruned"], 0)
        self.assertNotIn("line 00", memctl.read("notes"))
        self.assertIn("line 39", memctl.read("notes"))

    def test_prune_noop_under_budget(self):
        memctl.append("notes", "short")
        config.CFG["memory_budget_tokens"] = 800
        self.assertEqual(memctl.prune()["pruned"], 0)

    def test_status_shape(self):
        s = memctl.status()
        self.assertIn("budget", s)
        self.assertFalse(s["over"])
    
    def test_append_roundtrip_visible(self):
        memctl.append("notes", "the user prefers Helix")
        self.assertIn("Helix", memctl.read("notes"))

    def test_forget_removes_matching(self):
        memctl.append("notes", "temporary note")
        memctl.append("notes", "durable note")
        hits = 0
        for label in ("notes", "human"):
            body = memctl.read(label)
            kept = [l for l in body.splitlines() if "temporary note" not in l]
            hits += len(body.splitlines()) - len(kept)
            memctl.write(label, "\n".join(kept) + ("\n" if kept else ""))
        self.assertEqual(hits, 1)
        self.assertNotIn("temporary note", memctl.read("notes"))


if __name__ == "__main__":
    unittest.main()