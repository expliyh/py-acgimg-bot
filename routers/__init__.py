"""FastAPI router registrations for the administrative API."""

from . import dashboard, groups, private, configs

__all__ = [
    "dashboard",
    "groups",
    "private",
    "configs",
]
