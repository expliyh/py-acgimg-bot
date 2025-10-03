from __future__ import annotations

import logging

from registries import config_registry

logger = logging.getLogger(__name__)


def _parse_super_user_ids(value: str | bool | None) -> set[int]:
    if value in (None, False):
        return set()
    if value is True:
        return set()
    text = str(value)
    for ch in "\n\t\r":
        text = text.replace(ch, " ")
    tokens = [token.strip() for token in text.replace(",", " ").split(" ")]
    ids: set[int] = set()
    for token in tokens:
        if not token:
            continue
        try:
            ids.add(int(token))
        except ValueError:
            logger.debug("Skip invalid super user id token: %s", token)
    return ids


async def has_super_user_access(user_id: int | None) -> bool:
    """Return True when the user is allowed to run admin-only commands."""
    config_value = await config_registry.get_config("super_user")
    allowed = _parse_super_user_ids(config_value)
    if not allowed:
        return True
    if user_id is None:
        return False
    return user_id in allowed
