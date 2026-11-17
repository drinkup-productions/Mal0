"""Rate limits."""
import time
import unittest

from malo.core import config, idle


class Idle(unittest.TestCase):
    def setUp(self):
        config.CFG.clear()
        config.CFG["overlay"] = True
        idle._last_say = 0.0
        idle._last_user = 0.0

    def test_allowed_when_cold(self):
        idle._last_say = time.time() - idle.GAP - 1
        idle._last_user = time.time() - idle.AFTER_USER - 1
        self.assertTrue(idle.may_speak())

    def test_blocked_after_speaking(self):
        idle._last_say = time.time()
        idle._last_user = time.time() - idle.AFTER_USER - 1
        self.assertFalse(idle.may_speak())

    def test_blocked_after_user(self):
        idle._last_say = time.time() - idle.GAP - 1
        idle._last_user = time.time()
        self.assertFalse(idle.may_speak())

    def test_blocked_when_overlay_off(self):
        config.CFG["overlay"] = False
        self.assertFalse(idle.may_speak())


if __name__ == "__main__":
    unittest.main()