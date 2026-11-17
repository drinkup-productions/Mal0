"""Checks the artefacts each card should have produced."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
W = os.path.join(ROOT, "work")


def read(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def card1():
    got = read("work/card1/result.txt")
    if got is None:
        return "result.txt missing"
    lines = [l for l in got.splitlines() if l.strip()]
    if lines[:2] != ["beta", "alpha"]:
        return "result.txt should be beta then alpha, got %r" % lines[:2]
    return None


def card2():
    got = read("work/card2/excerpt.txt")
    if got is None:
        return "excerpt.txt missing"
    lines = [l for l in got.splitlines() if l.strip()]
    if len(lines) < 3:
        return "expected 3 non-empty lines, got %d" % len(lines)
    return None


def card3():
    got = read("work/card3/tokens.txt")
    if got is None:
        return "tokens.txt missing"
    if not got.strip().isdigit():
        return "tokens.txt should be an integer, got %r" % got.strip()[:40]
    return None


def card3b():
    got = read("work/card3/recall.txt")
    if got is None:
        return "recall.txt missing"
    if "quince" not in got.lower():
        return "recall.txt should mention quince"
    return None


def card4():
    got = read("work/card4/job.txt")
    if got is None:
        return "job.txt missing (write the job id there)"
    if not got.strip().startswith("job-"):
        return "job.txt should hold the job id"
    return None


def card5():
    got = read("work/card5/missing.txt")
    if got is None:
        return "missing.txt was never created"
    if "recovered" not in got:
        return "missing.txt should contain 'recovered'"
    return None


def card6():
    got = read("work/card6/answer.txt")
    if got is None:
        return "answer.txt missing"
    if "12" not in got:
        return "answer.txt should name section 12"
    return None


CARDS = {
    "1 files": card1,
    "2 web": card2,
    "3 memory": card3,
    "3b recall": card3b,
    "4 broker": card4,
    "5 recovery": card5,
    "6 paging": card6,
}


def main(argv):
    want = argv[1:] or list(CARDS)
    failed = 0
    for name in CARDS:
        if want and not any(name.startswith(w) for w in want):
            continue
        err = CARDS[name]()
        print("%-12s %s" % (name, "PASS" if err is None else "FAIL: " + err))
        failed += bool(err)
    print("\n%d failed" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))