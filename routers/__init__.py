"""FastAPI router registrations for the administrative API."""

from . import dashboard, groups, private, configs, commands, image_push

__all__ = [
    "dashboard",
    "groups",
    "private",
    "configs",
    "commands",
    "image_push",
]
