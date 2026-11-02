import os
import sys
import tempfile

os.environ["MALO_DATA"] = tempfile.mkdtemp(prefix="malo-mem-")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from malo.core import config, memory

config.reset()
memory.close()
assert memory.stats()["total"] == 0

a = memory.add("prefers the Helix editor", "user", 0.8)
assert a
assert memory.add("prefers the Helix editor", "user", 0.8) == a, "dedupe failed"
assert memory.stats()["total"] == 1

b = memory.add("workspace uses Python 3.15", "machine", 0.7)
rows = memory.recall("what editor does he like")
assert rows and rows[0]["id"] == a, "recall ranking failed"

memory.set_pinned(b)
rows = memory.recall("what editor")
assert rows[0]["id"] == b, "pin did not float"

assert len(memory.recall("editor", limit=1, budget=5)) == 1, "limit ignored"

memory.add("prefers the Helix editor", "user", 0.8)
assert memory.consolidate() >= 0
assert memory.stats()["total"] == 2, "consolidate duplicated"

assert memory.forget(mid=a) == 1
assert memory.stats()["total"] == 1
assert memory.forget(text="nothing here") == 0

print("memory ok")