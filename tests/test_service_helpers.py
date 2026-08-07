from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest

from services import command_history
from services import group_guard
from services import original_image_manager as original_images
from services.file_service import file_lock
from services.schema_migrator import (
    _ensure_column_bigint,
    _get_current_version,
    _record_migration,
)
from services.storage_service.local import LocalStorage


@pytest.mark.asyncio
async def test_local_storage_loads_config_and_uploads_to_nested_folder(tmp_path, monkeypatch):
    config = SimpleNamespace(root_path=str(tmp_path), base_url="https://cdn.example/files/")
    get_config = AsyncMock(return_value=config)
    monkeypatch.setattr(
        "services.storage_service.local.config_registry.get_local_storage_config",
        get_config,
    )
    storage = LocalStorage()

    url = await storage.upload(b"image-data", "sample.jpg", r"pixiv\2026")

    assert url == "https://cdn.example/files/pixiv/2026/sample.jpg"
    assert (tmp_path / "pixiv" / "2026" / "sample.jpg").read_bytes() == b"image-data"
    get_config.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_local_storage_returns_relative_path_without_base_url(tmp_path, monkeypatch):
    config = SimpleNamespace(root_path=str(tmp_path), base_url=None)
    monkeypatch.setattr(
        "services.storage_service.local.config_registry.get_local_storage_config",
        AsyncMock(return_value=config),
    )
    storage = LocalStorage()

    assert await storage.upload(b"x", "file.bin") == "file.bin"


def test_file_locks_are_reused_and_can_be_deleted():
    file_lock.file_locks.clear()
    dictionary_lock, first = file_lock.get_lock("one")
    assert dictionary_lock is file_lock.get_dick_lock()
    assert file_lock.get_lock("one")[1] is first

    file_lock.del_lock("one")
    assert file_lock.get_lock("one")[1] is not first


@pytest.mark.asyncio
async def test_keyword_rule_rejects_empty_long_and_invalid_regex_without_database_access(
    monkeypatch,
):
    new_session = MagicMock()
    monkeypatch.setattr(group_guard.engine, "new_session", new_session)

    with pytest.raises(ValueError, match="不能为空"):
        await group_guard.add_keyword_rule(1, "   ")
    with pytest.raises(ValueError, match="长度不能超过"):
        await group_guard.add_keyword_rule(1, "x" * (group_guard.MAX_KEYWORD_PATTERN_LENGTH + 1))
    with pytest.raises(ValueError, match="正则表达式无效"):
        await group_guard.add_keyword_rule(1, "[", is_regex=True)

    new_session.assert_not_called()


@pytest.mark.asyncio
async def test_guard_cache_invalidation_and_empty_ensure_settings(monkeypatch):
    settings = group_guard.GuardSettings(1, True, 60, None, False, True)
    group_guard._settings_cache[1] = (settings, datetime.now(timezone.utc))
    group_guard._keyword_cache[1] = ([], datetime.now(timezone.utc))

    await group_guard._invalidate_settings_cache(1)
    await group_guard._invalidate_keyword_cache(1)
    assert 1 not in group_guard._settings_cache
    assert 1 not in group_guard._keyword_cache

    new_session = MagicMock()
    monkeypatch.setattr(group_guard.engine, "new_session", new_session)
    await group_guard.ensure_settings([0, 0])
    new_session.assert_not_called()


@pytest.mark.asyncio
async def test_schema_helpers_select_version_and_use_dialect_specific_upsert():
    result = MagicMock()
    result.scalar.return_value = None
    connection = AsyncMock()
    connection.execute.return_value = result
    connection.dialect.name = "sqlite"

    assert await _get_current_version(connection, "schema_migrations") == 0
    await _record_migration(connection, "schema_migrations", 2)
    statement, parameters = connection.execute.await_args_list[-1].args
    assert "ON CONFLICT(version)" in str(statement)
    assert parameters == {"version": 2}

    connection.dialect.name = "mysql"
    await _record_migration(connection, "schema_migrations", 3)
    statement = connection.execute.await_args_list[-1].args[0]
    assert "ON DUPLICATE KEY" in str(statement)


@pytest.mark.asyncio
async def test_ensure_column_bigint_skips_missing_or_already_compatible_columns():
    connection = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = None
    connection.execute.return_value = result
    await _ensure_column_bigint(connection, "db", "users", "id", allow_autoincrement=False)
    assert connection.execute.await_count == 1

    result.mappings.return_value.first.return_value = {
        "DATA_TYPE": "bigint",
        "IS_NULLABLE": "NO",
        "COLUMN_DEFAULT": None,
        "COLUMN_COMMENT": None,
        "EXTRA": "",
    }
    await _ensure_column_bigint(connection, "db", "users", "id", allow_autoincrement=False)
    assert connection.execute.await_count == 2


@pytest.mark.asyncio
async def test_history_and_markup_failures_are_best_effort(monkeypatch):
    monkeypatch.setattr(command_history, "_persist_history", AsyncMock(side_effect=RuntimeError("db")))

    @command_history.command_logger("ping")
    async def handler(update, context):
        return "pong"

    assert await handler(SimpleNamespace(), SimpleNamespace()) == "pong"

    original_images._requests.clear()
    original_images._latest_token_by_chat.clear()
    previous = original_images.OriginalImageRequest("old", 1, 2, 3, 0, message_id=10)
    current = original_images.OriginalImageRequest("new", 1, 2, 4, 0, message_id=11)
    bot = AsyncMock()
    await original_images.register_request(bot, previous)
    bot.edit_message_reply_markup.side_effect = BadRequest("gone")
    await original_images.register_request(bot, current)
    assert await original_images.get_request("new") is current
