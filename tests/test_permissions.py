from unittest.mock import AsyncMock

import pytest

from services import permissions


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, set()),
        (False, set()),
        (True, set()),
        ("1, 2\n3\tinvalid 2", {1, 2, 3}),
        ("", set()),
    ],
)
def test_parse_super_user_ids(value, expected):
    assert permissions._parse_super_user_ids(value) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured", "user_id", "expected"),
    [("10,20", 20, True), ("10,20", 30, False), ("10", None, False), (None, None, True)],
)
async def test_has_super_user_access(monkeypatch, configured, user_id, expected):
    get_config = AsyncMock(return_value=configured)
    monkeypatch.setattr(permissions.config_registry, "get_config", get_config)

    assert await permissions.has_super_user_access(user_id) is expected
    get_config.assert_awaited_once_with("super_user")
