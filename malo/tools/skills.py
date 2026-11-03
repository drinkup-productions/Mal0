"""Skill authoring tools."""
from ..core import skills


def write_skill(name, code):
    return skills.write(name, code)


def list_skills():
    return skills.listing()


def reload_skills():
    skills.load_all()
    return {"tools": sorted(skills.SPECS)}