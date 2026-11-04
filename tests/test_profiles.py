"""Workspace profile behaviour: jail widening, filters, brief propagation."""
import copy
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from malo.core import config, profiles
from malo.tools import core


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "data")
        os.makedirs(self.root, exist_ok=True)
        self.p = SimpleNamespace(
            root=self.root,
            config=os.path.join(self.root, "config.json"),
            output=self.root, log=os.path.join(self.root, "m.log"),
            feedback=os.path.join(self.root, "f.jsonl"),
            personas=os.path.join(self.root, "p.json"),
            personas_dir=os.path.join(self.root, "personas"),
            sfx_dir=self.root, workspace_default=self.tmp)
        self._old = config._paths
        config._paths = self.p
        config.CFG.clear()
        config.CFG.update(copy.deepcopy(config.DEFAULT_CFG))

    def tearDown(self):
        config._paths = self._old
        config.CFG.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_profile_is_the_workspace(self):
        self.assertEqual(profiles.active_name(), "default")
        self.assertEqual(profiles.roots(),
                         [os.path.normcase(os.path.realpath(self.tmp))])
        self.assertTrue(core._inside(os.path.join(self.tmp, "x.txt")))

    def test_use_rewrites_the_jail(self):
        other = os.path.join(self.tmp, "proj")
        os.makedirs(other)
        profiles.save("work", [other], ["code"], "finish the patch")
        r = profiles.use("work")
        self.assertEqual(r["profile"], "work")
        self.assertTrue(core._inside(os.path.join(other, "a.py")))
        self.assertFalse(core._inside(os.path.join(self.tmp, "elsewhere.txt")))
        self.assertEqual(config.get("wake_brief"), "finish the patch")

    def test_filter_matches_title_or_process(self):
        profiles.save("work", [self.tmp], ["code", "visual studio"])
        self.assertTrue(profiles.visible("work", "main.py - Visual Studio Code"))
        self.assertFalse(profiles.visible("work", "Steam"))
        profiles.save("open", [self.tmp], [])
        self.assertTrue(profiles.visible("open", "Steam"))

    def test_save_dedupes_and_caps(self):
        many = [os.path.join(self.tmp, "d%d" % i) for i in range(20)]
        profiles.save("big", many, ["a"] * 50)
        p = profiles.get("big")
        self.assertEqual(len(p["roots"]), profiles.MAX_ROOTS)
        self.assertEqual(len(p["windows"]), profiles.MAX_WINDOWS)

    def test_remove_falls_back_to_default(self):
        profiles.save("tmp", [self.tmp])
        profiles.use("tmp")
        profiles.remove("tmp")
        self.assertEqual(profiles.active_name(), "default")
        self.assertEqual(config.get("workspace"),
                         os.path.normcase(os.path.realpath(self.tmp)))

    def test_unknown_profile_is_refused(self):
        self.assertIn("error", profiles.use("nope"))


if __name__ == "__main__":
    unittest.main()