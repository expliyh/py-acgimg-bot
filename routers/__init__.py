"""FastAPI router registrations for the administrative API."""

from . import dashboard, groups, private, configs, commands

__all__ = [
    "dashboard",
    "groups",
    "private",
    "configs",
    "commands",
]
