"""Unprompted line rate limiting."""
import time

from . import config

GAP = 20 * 60
AFTER_USER = 10 * 60

_last_say = 0.0
_last_user = 0.0


def user_spoke():
    global _last_user
    _last_user = time.time()


def may_speak():
    if not config.get("overlay", True):
        return False
    now = time.time()
    if now - _last_say < GAP:
        return False
    if now - _last_user < AFTER_USER:
        return False
    return True


def spoke():
    global _last_say
    _last_say = time.time()