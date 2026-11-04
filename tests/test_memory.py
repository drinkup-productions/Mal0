"""Memory behaviour. Owns its own MALO_DATA per test."""
import os
import shutil
import tempfile
import unittest

from malo.core import config, memory

TMP = None


def setUpModule():
    global TMP
    TMP = tempfile.mkdtemp(prefix="malo-mem-")
    config.reset()
    memory.close()


def tearDownModule():
    memory.close()
    os.environ.pop("MALO_DATA", None)
    config.reset()
    shutil.rmtree(TMP, ignore_errors=True)


class Memory(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)
        os.environ["MALO_DATA"] = self.d
        config.reset()
        config.load()
        memory.close()

    def tearDown(self):
        memory.close()
        shutil.rmtree(self.d, ignore_errors=True)

    def test_dedupe(self):
        a = memory.add("prefers the Helix editor", "user", 0.8)
        self.assertTrue(a)
        self.assertEqual(memory.add("prefers the Helix editor", "user", 0.8), a)
        self.assertEqual(memory.stats()["total"], 1)

    def test_recall_ranks_the_match_first(self):
        a = memory.add("prefers the Helix editor", "user", 0.8)
        memory.add("workspace uses Python 3.15", "machine", 0.7)
        rows = memory.recall("what editor does he like")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["id"], a)

    def test_pin_floats(self):
        memory.add("prefers the Helix editor", "user", 0.8)
        b = memory.add("workspace uses Python 3.15", "machine", 0.7)
        memory.set_pinned(b, True)
        self.assertEqual(memory.recall("what editor")[0]["id"], b)

    def test_limit_and_budget(self):
        for i in range(5):
            memory.add("padding entry %d with some length to it" % i, "user", 0.5)
        self.assertEqual(len(memory.recall("padding", limit=1, budget=5)), 1)

    def test_consolidate_does_not_duplicate(self):
        memory.add("prefers the Helix editor", "user", 0.8)
        memory.add("workspace uses Python 3.15", "machine", 0.7)
        self.assertGreaterEqual(memory.consolidate(), 0)
        self.assertEqual(memory.stats()["total"], 2)

    def test_forget(self):
        a = memory.add("prefers the Helix editor", "user", 0.8)
        self.assertEqual(memory.forget(mid=a), 1)
        self.assertEqual(memory.stats()["total"], 0)
        self.assertEqual(memory.forget(text="nothing here"), 0)


if __name__ == "__main__":
    unittest.main()