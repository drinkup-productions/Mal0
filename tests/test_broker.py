"""Broker queue semantics against a temp db."""
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from malo.core import broker

TMP = None


def setUpModule():
    global TMP
    TMP = tempfile.mkdtemp(prefix="malo-broker-")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Q(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)
        self._patch = mock.patch.object(broker, "db_path",
                                        lambda: os.path.join(self.d, "b.db"))
        self._patch.start()
        self.c = broker.connect()

    def tearDown(self):
        self.c.close()
        self._patch.stop()
        shutil.rmtree(self.d, ignore_errors=True)

    def test_dedupe(self):
        a, fresh = broker.enqueue(self.c, "job", "large", "idem-1", "")
        b, fresh2 = broker.enqueue(self.c, "job", "large", "idem-1", "")
        self.assertEqual(a, b)
        self.assertTrue(fresh)
        self.assertFalse(fresh2)

    def test_claim_is_exclusive(self):
        broker.enqueue(self.c, "one", "large", "i1", "")
        self.assertIsNotNone(broker.claim(self.c))
        self.assertIsNone(broker.claim(self.c))

    def test_claim_order(self):
        ids = [broker.enqueue(self.c, "job %d" % i, "large", "i%d" % i, "")[0]
               for i in range(3)]
        got = [broker.claim(self.c)["id"] for _ in range(3)]
        self.assertEqual(got, ids)

    def test_attempts_increment(self):
        jid, _ = broker.enqueue(self.c, "one", "large", "i1", "")
        broker.claim(self.c)
        row = self.c.execute("SELECT attempts FROM jobs WHERE id=?",
                             (jid,)).fetchone()
        self.assertEqual(row["attempts"], 1)

    def test_requeue_stale(self):
        jid, _ = broker.enqueue(self.c, "one", "large", "i1", "")
        broker.claim(self.c)
        broker.requeue_stale(self.c)
        row = self.c.execute("SELECT status FROM jobs WHERE id=?",
                             (jid,)).fetchone()
        self.assertEqual(row["status"], "queued")

    def test_requeue_fails_at_ceiling(self):
        jid, _ = broker.enqueue(self.c, "one", "large", "i1", "")
        self.c.execute("UPDATE jobs SET status='claimed', attempts=3 WHERE id=?",
                       (jid,))
        broker.requeue_stale(self.c)
        row = self.c.execute("SELECT status FROM jobs WHERE id=?",
                             (jid,)).fetchone()
        self.assertEqual(row["status"], "failed")

    def test_expiry(self):
        jid, _ = broker.enqueue(self.c, "one", "large", "i1", "")
        self.c.execute("UPDATE jobs SET created=? WHERE id=?",
                       (time.time() - 90000, jid))
        broker._sweep(self.c)
        row = self.c.execute("SELECT status FROM jobs WHERE id=?",
                             (jid,)).fetchone()
        self.assertEqual(row["status"], "expired")

    def test_finish_marks_done(self):
        jid, _ = broker.enqueue(self.c, "one", "large", "i1", "")
        broker.claim(self.c)
        broker.finish(self.c, jid, result="ok")
        row = self.c.execute("SELECT status FROM jobs WHERE id=?",
                             (jid,)).fetchone()
        self.assertEqual(row["status"], "done")


if __name__ == "__main__":
    unittest.main()