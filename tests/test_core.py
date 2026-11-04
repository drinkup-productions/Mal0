"""Behavioural tests for core/. Run: python -m unittest discover -s tests -q"""
import os
import shutil
import tempfile
import unittest

from malo.core import config, memory, perm, selfdev, skills
from malo.tools import core as tools, registry

TMP = None
OLD = None


def setUpModule():
    global TMP, OLD
    TMP = tempfile.mkdtemp(prefix="malo-test-")
    OLD = os.environ.get("MALO_DATA")
    os.environ["MALO_DATA"] = TMP
    config.reset()
    config.load()
    config.CFG["workspace"] = os.path.join(TMP, "ws")
    os.makedirs(config.CFG["workspace"], exist_ok=True)
    config.CFG["repo"] = os.path.join(TMP, "repo")
    os.makedirs(os.path.join(config.CFG["repo"], "malo"), exist_ok=True)
    with open(os.path.join(config.CFG["repo"], "malo", "probe.py"), "w") as fh:
        fh.write("def recall():\n    return 1\n")
    config.CFG["self_test_cmd"] = "python -c \"print('ok')\""


def tearDownModule():
    if OLD:
        os.environ["MALO_DATA"] = OLD
    else:
        os.environ.pop("MALO_DATA", None)
    config.reset()
    shutil.rmtree(TMP, ignore_errors=True)

def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()
        
class Jail(unittest.TestCase):
    def test_outside_refused(self):
        with self.assertRaises(ValueError):
            tools._resolve(r"C:\Windows\win.ini")

    def test_workspace_allowed(self):
        p = tools._resolve("a.txt")
        self.assertTrue(p.startswith(config.CFG["workspace"]))

    def test_repo_allowed(self):
        p = tools._resolve(os.path.join(config.CFG["repo"], "malo", "probe.py"))
        self.assertTrue(os.path.isfile(p))


class Undo(unittest.TestCase):
    def test_write_then_undo(self):
        tools.write("u.txt", "one")
        tools.write("u.txt", "two")
        self.assertIn("two", tools.read("u.txt")["content"])
        tools.undo()
        self.assertIn("one", tools.read("u.txt")["content"])

    def test_edit_is_snapshotted(self):
        tools.write("e.txt", "alpha")
        tools.edit("e.txt", "alpha", "beta")
        self.assertIn("beta", tools.read("e.txt")["content"])
        tools.undo()
        self.assertIn("alpha", tools.read("e.txt")["content"])


class Memory(unittest.TestCase):
    def test_roundtrip(self):
        mid = memory.add("the user prefers Helix", "user", 0.9)
        rows = memory.recall("helix")
        self.assertTrue(any(r["id"] == mid for r in rows))

    def test_pinned_floats(self):
        memory.add("deploys to tethys", "machine", 0.3)
        mid = memory.add("zebra fact unrelated", "user", 0.2)
        memory.set_pinned(mid, True)
        self.assertEqual(memory.recall("helix")[0]["id"], mid)

    def test_forget(self):
        mid = memory.add("temporary note", "user", 0.4)
        self.assertEqual(memory.forget(mid), 1)
        self.assertFalse(any(r["id"] == mid for r in memory.recall("temporary")))

    def test_budget_caps_rows(self):
        for i in range(5):
            memory.add("padding entry %d with some length to it" % i, "user", 0.5)
        self.assertLessEqual(len(memory.recall("padding", budget=40)), 2)


class Perm(unittest.TestCase):
    def test_selfedit_off_by_default(self):
        self.assertFalse(perm.allowed("apply", config.CFG))

    def test_denied_tool_errors(self):
        config.CFG["perm"] = {"selfedit": False}
        self.assertIn("permission denied", registry.run("apply", {"pid": "1"})["error"])

    def test_toggle_on(self):
        config.CFG["perm"] = {"input": False}
        self.assertFalse(perm.allowed("click", config.CFG))
        config.CFG["perm"] = {"input": True}
        self.assertTrue(perm.allowed("click", config.CFG))

    def test_mcp_is_network(self):
        self.assertEqual(perm.cls("ddg__search"), "network")


class Registry(unittest.TestCase):
    def test_unknown_tool(self):
        self.assertIn("unknown tool", registry.run("nope", {})["error"])

    def test_specs_include_core(self):
        names = [s["function"]["name"] for s in registry.all_specs()]
        self.assertIn("read", names)
        self.assertIn("uia_act", names)


class Skills(unittest.TestCase):
    def test_write_and_call(self):
        code = (
            "SPECS = [{'type': 'function', 'function': {'name': 'probe_echo',\n"
            "          'description': 'echo', 'parameters': {'type': 'object',\n"
            "          'properties': {'v': {'type': 'string'}}, 'required': ['v']}}}]\n"
            "def probe_echo(v):\n"
            "    return {'echo': v}\n"
        )
        out = skills.write("probe", code)
        self.assertIn("saved", out, out)
        self.assertEqual(skills.call("probe_echo", {"v": "hi"})["echo"], "hi")
        self.assertEqual(registry.run("probe_echo", {"v": "hi"})["echo"], "hi")

    def test_broken_skill_reported(self):
        skills.write("broken", "SPECS = [oops\n")
        self.assertIn("broken", skills.BAD)

    def test_failed_skill_does_not_break_others(self):
        skills.write("good", "def noop():\n    return 1\n")
        self.assertIn("skills", skills.listing())


class SelfDev(unittest.TestCase):
    def test_propose_and_apply_reverts_on_failure(self):
        config.CFG["self_test_cmd"] = "python -c \"import sys; sys.exit(1)\""
        rel = "malo/probe.py"
        target = os.path.join(config.CFG["repo"], rel)
        before = _read(target)
        out = selfdev.propose("t", "r", {rel: "def recall():\n    return 2\n"})
        self.assertIn("proposal", out, out)
        res = selfdev.apply(out["proposal"])
        self.assertFalse(res["applied"])
        self.assertTrue(res["reverted"])
        self.assertEqual(_read(target), before)

    def test_apply_keeps_change_when_tests_pass(self):
        config.CFG["self_test_cmd"] = "python -c \"print('ok')\""
        rel = "malo/probe.py"
        target = os.path.join(config.CFG["repo"], rel)
        out = selfdev.propose("t2", "r", {rel: "def recall():\n    return 3\n"})
        res = selfdev.apply(out["proposal"])
        self.assertTrue(res["applied"])
        self.assertIn("return 3", _read(target))
        
class Schema(unittest.TestCase):
    def test_version_stamped(self):
        from malo.core import memory
        memory.close()
        memory.conn()
        v = memory.conn().execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(v, memory.SCHEMA_VERSION)

    def test_migration_runs_once(self):
        from malo.core import memory
        memory.close()
        memory.MIGRATIONS[999] = "CREATE TABLE IF NOT EXISTS probe_tbl (x INTEGER);"
        try:
            memory.conn()
            names = [r[0] for r in memory.conn().execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertIn("probe_tbl", names)
            v = memory.conn().execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(v, 999)
        finally:
            memory.MIGRATIONS.pop(999, None)
            c = memory.conn()
            c.execute("PRAGMA user_version = %d" % memory.SCHEMA_VERSION)
            c.commit()
            memory.close()


if __name__ == "__main__":
    unittest.main()