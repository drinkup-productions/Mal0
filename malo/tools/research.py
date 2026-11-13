"""Manual research trigger."""
from ..core import config, interests


def research_now(topic=""):
    if topic:
        interests.mark(topic)
        return {"topic": topic}
    return {"topic": interests.pick()}


def interest_add(topic):
    rows = list(config.get("interests") or [])
    if topic and topic not in rows:
        rows.append(topic)
        config.CFG["interests"] = rows
        config.save()
    return {"interests": rows}


def interest_list():
    return {"interests": config.get("interests") or [],
            "recent": config.get("interest_recent") or {}}