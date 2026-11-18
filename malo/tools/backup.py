"""Backup inspection and restore."""
from ..core import backup


def backup_list(pattern="", limit=30):
    return backup.listing(pattern, limit)


def backup_restore(row_id, path=""):
    return backup.restore(row_id, path or None)


def backup_stats():
    return backup.stats()


def bash_archives(limit=10):
    return backup.archives(limit)


def bash_restore(archive, path):
    return backup.restore_member(archive, path)