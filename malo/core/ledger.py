"""Token and spend accounting."""
import time

SPEND = {"date": time.strftime("%Y-%m-%d"), "usd": 0.0, "tokens": 0, "turns": 0}
SESSION = {"usd": 0.0, "tokens": 0}


def add(usd, tokens=0):
    SPEND["usd"] = round(SPEND.get("usd", 0.0) + max(0.0, usd), 6)
    SPEND["tokens"] = SPEND.get("tokens", 0) + int(tokens)
    SPEND["turns"] = SPEND.get("turns", 0) + 1
    SESSION["usd"] += max(0.0, usd)
    SESSION["tokens"] += int(tokens)
    return SPEND["usd"]


def over_budget(cap):
    return cap > 0 and SPEND.get("usd", 0) >= cap