"""The apply gate: revert on failure, revert on raise, refuse stale and double applies."""
import copy
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

from malo.core import config, selfdev

FAIL = '"%s" -c "import sys; sys.exit(1)"' % sys.executable
PASS = '"%s" -c "pass"' % sys.executable


class ApplyGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "data")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.root)
        os.makedirs(self.repo)
        self.target = os.path.join(self.repo, "mod.py")
        with open(self.target, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 1\n")
        p = SimpleNamespace(root=self.root, config=os.path.join(self.root, "c.json"),
                            output=self.root, log=os.path.join(self.root, "m.log"),
                            feedback=os.path.join(self.root, "f.jsonl"),
                            personas=os.path.join(self.root, "p.json"),
                            personas_dir=os.path.join(self.root, "personas"),
                            sfx_dir=self.root, workspace_default=self.tmp)
        self._old = config._paths
        config._paths = p
        config.CFG.clear()
        config.CFG.update(copy.deepcopy(config.DEFAULT_CFG))
        config.CFG["repo"] = self.repo
        config.CFG["self_test_cmd"] = PASS

    def tearDown(self):
        config._paths = self._old
        config.CFG.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _propose(self, text):
        return selfdev.propose("t", "r", {"mod.py": text})

    def _content(self):
        with open(self.target, encoding="utf-8") as fh:
            return fh.read()

    def test_failed_tests_revert_the_file(self):
        config.CFG["self_test_cmd"] = FAIL
        pid = self._propose("VALUE = 2\n")["proposal"]
        r = selfdev.apply(pid)
        self.assertFalse(r["applied"])
        self.assertTrue(r["reverted"])
        self.assertEqual(self._content(), "VALUE = 1\n")
        self.assertNotIn("applied_at", self._meta(pid))

    def test_raising_test_command_still_reverts(self):
        config.CFG["self_test_cmd"] = "definitely-not-a-real-command-xyz"
        pid = self._propose("VALUE = 2\n")["proposal"]
        r = selfdev.apply(pid)
        self.assertFalse(r["applied"])
        self.assertEqual(self._content(), "VALUE = 1\n")

    def test_pass_installs_and_stamps(self):
        pid = self._propose("VALUE = 2\n")["proposal"]
        r = selfdev.apply(pid)
        self.assertTrue(r["applied"])
        self.assertEqual(self._content(), "VALUE = 2\n")
        self.assertIn("applied_at", self._meta(pid))

    def test_second_apply_refused_without_force(self):
        pid = self._propose("VALUE = 2\n")["proposal"]
        selfdev.apply(pid)
        self.assertIn("error", selfdev.apply(pid))
        self.assertTrue(selfdev.apply(pid, force=True)["applied"])

    def test_drift_refused(self):
        pid = self._propose("VALUE = 2\n")["proposal"]
        with open(self.target, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 99\n")
        self.assertIn("error", selfdev.apply(pid))
        self.assertEqual(self._content(), "VALUE = 99\n")

    def test_outside_repo_refused(self):
        r = selfdev.propose("t", "r", {"../escape.py": "x = 1\n"})
        self.assertIn("error", r)

    def test_discard_removes(self):
        pid = self._propose("VALUE = 2\n")["proposal"]
        self.assertEqual(selfdev.discard(pid), {"discarded": pid})
        self.assertIn("error", selfdev.apply(pid))

    def _meta(self, pid):
        import json
        with open(os.path.join(self.root, "proposals", pid, "meta.json")) as fh:
            return json.load(fh)


if __name__ == "__main__":
    unittest.main()