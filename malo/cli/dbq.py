"""Run one SQL statement against the broker DB.

    python -m malo.cli.dbq "select id,status,attempts from jobs where idem='c2'"
"""
import os
import sqlite3
import sys

from ..core import config


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        raise SystemExit("usage: dbq <sql>")
    sql = " ".join(argv)
    config.load()
    path = os.path.join(config.paths().root, "broker.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql)
    if cur.description:
        print(" | ".join(d[0] for d in cur.description))
        for row in cur.fetchall():
            print(" | ".join("" if v is None else str(v) for v in row))
    else:
        print("rows", cur.rowcount)
    conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())