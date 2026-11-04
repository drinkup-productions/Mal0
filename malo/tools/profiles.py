"""Profile tools. Switching a profile rewrites the jail in one move."""
from ..core import profiles


def _split(v):
    if isinstance(v, list):
        return v
    return [x for x in str(v or "").replace("\n", ";").split(";") if x.strip()]


def profile_list():
    return {"active": profiles.active_name(),
            "profiles": "\n".join("%s%s  roots:%d windows:%d%s"
                                  % ("* " if r["active"] else "  ", r["name"],
                                     r["roots"], r["windows"],
                                     "  [brief]" if r["brief"] else "")
                                  for r in profiles.rows())}


def profile_show(name=None):
    p = profiles.get(name)
    return {"profile": p["name"], "roots": p["roots"],
            "windows": p["windows"] or "(all)", "brief": p["brief"] or "(none)"}


def profile_use(name):
    return profiles.use(name)


def profile_save(name, roots=None, windows=None, brief=None):
    return profiles.save(name, _split(roots) if roots is not None else None,
                         _split(windows) if windows is not None else None, brief)


def profile_delete(name):
    return profiles.remove(name)