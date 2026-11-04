"""Task boundary: the newest instruction wins, and old chatter leaves the prompt."""
import unittest

from malo.core import engine, tasks


class Tasks(unittest.TestCase):
    def tearDown(self):
        tasks.clear()

    def test_begin_supersedes(self):
        tasks.begin("first thing")
        tasks.begin("second thing")
        self.assertEqual(tasks.current()["text"], "second thing")

    def test_clear(self):
        tasks.begin("x")
        tasks.clear()
        self.assertEqual(tasks.current()["text"], "")

    def test_whitespace_collapsed(self):
        self.assertEqual(tasks.begin("  a \n b  "), "a b")


class Slim(unittest.TestCase):
    def test_keeps_current_turn_tool_calls(self):
        msgs = [
            {"role": "user", "content": "old task"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "big result"},
            {"role": "assistant", "content": "part way"},
            {"role": "user", "content": "new task"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "2"}]},
            {"role": "tool", "tool_call_id": "2", "content": "current result"},
        ]
        out = engine._slim(msgs)
        self.assertEqual(out[0], {"role": "user", "content": "old task"})
        self.assertEqual(out[1], {"role": "assistant", "content": "part way"})
        self.assertNotIn("big result", [m.get("content") for m in out])
        self.assertIn("current result", [m.get("content") for m in out])
        self.assertEqual(len(out), 5)

    def test_empty(self):
        self.assertEqual(engine._slim([]), [])

    def test_single_user_message_survives(self):
        self.assertEqual(engine._slim([{"role": "user", "content": "hi"}]),
                         [{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()