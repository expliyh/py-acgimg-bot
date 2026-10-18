"""Regression coverage for Telegram authorization and handler edge cases."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import BadRequest


@pytest.mark.parametrize("configured", [None, False, "", " \n\t", "invalid"])
async def test_admin_denies_before_building_panel(monkeypatch, configured):
    from handlers.command_handlers import admin_handler
    from services import permissions

    monkeypatch.setattr(permissions.config_registry, "get_config", AsyncMock(return_value=configured))
    panel = AsyncMock()
    monkeypatch.setattr(admin_handler.messase_generator, "bot_admin", panel)
    reply = AsyncMock()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=2), effective_chat=SimpleNamespace(id=2, type="private"),
        effective_message=SimpleNamespace(reply_text=reply),
    )
    await admin_handler.admin_handler_func.__wrapped__(update, SimpleNamespace())
    reply.assert_awaited_once()
    panel.assert_not_awaited()


@pytest.mark.parametrize("configured", [None, False, "", " \n\t", "invalid"])
async def test_bot_callback_denies_without_configured_admin_ids(monkeypatch, configured):
    from services import permissions

    module = importlib.import_module("handlers.callback_handlers.conf_handlers.bot.bot_conf_handler")
    monkeypatch.setattr(permissions.config_registry, "get_config", AsyncMock(return_value=configured))
    handler = AsyncMock()
    monkeypatch.setitem(module.handler_map, "feature", handler)
    query = SimpleNamespace(answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=2))
    await module.bot_conf_handler_func(update, SimpleNamespace(), ["feature", "allow_r18g", "on"])
    handler.assert_not_awaited()
    query.answer.assert_awaited_once_with("您没有权限修改机器人配置。", show_alert=True)


@pytest.mark.parametrize("allowed", [True, False])
async def test_bot_callback_checks_current_permissions(monkeypatch, allowed):
    module = importlib.import_module("handlers.callback_handlers.conf_handlers.bot.bot_conf_handler")
    monkeypatch.setattr(module, "has_super_user_access", AsyncMock(return_value=allowed))
    handler = AsyncMock()
    monkeypatch.setitem(module.handler_map, "feature", handler)
    update = SimpleNamespace(callback_query=SimpleNamespace(answer=AsyncMock()), effective_user=SimpleNamespace(id=2))
    context = SimpleNamespace()
    await module.bot_conf_handler_func(update, context, ["feature", "allow_r18g", "on"])
    if allowed:
        handler.assert_awaited_once_with(update, context, ["allow_r18g", "on"])
    else:
        handler.assert_not_awaited()
        assert update.callback_query.answer.call_args.kwargs["show_alert"] is True


@pytest.mark.parametrize("name", ["set_pixiv_token", "set_backblaze_appid", "set_cache_redis", "set_cache_ttl"])
async def test_config_submission_rechecks_revoked_permissions(monkeypatch, name):
    module = importlib.import_module(f"handlers.message_handlers.{name}")
    monkeypatch.setattr(module, "has_super_user_access", AsyncMock(return_value=False))
    monkeypatch.setattr(module.active_message_handler_registry, "get", AsyncMock(return_value=f"{name}:123"))
    delete = AsyncMock()
    monkeypatch.setattr(module.active_message_handler_registry, "delete", delete)
    write = AsyncMock()
    monkeypatch.setattr(module.config_registry, "update_config", write)
    message = SimpleNamespace(text="secret", chat=SimpleNamespace(type="private"), reply_text=AsyncMock())
    await getattr(module, name)(SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=2)), SimpleNamespace())
    delete.assert_awaited_once_with(user_id=2)
    message.reply_text.assert_awaited_once()
    write.assert_not_awaited()


async def test_pinfo_without_args_replies_with_usage(monkeypatch):
    from handlers.command_handlers import p_info_handler

    monkeypatch.setattr(p_info_handler, "has_super_user_access", AsyncMock(return_value=True))
    monkeypatch.setattr(p_info_handler.pixiv, "enabled", True)
    fetch = AsyncMock()
    monkeypatch.setattr(p_info_handler.pixiv, "get_illust_info_by_pixiv_id", fetch)
    reply = AsyncMock()
    await p_info_handler.p_info_func.__wrapped__(
        SimpleNamespace(effective_user=SimpleNamespace(id=1), message=SimpleNamespace(reply_text=reply, message_id=10)),
        SimpleNamespace(args=[]),
    )
    assert "/pinfo" in reply.call_args.kwargs["text"]
    fetch.assert_not_awaited()


async def test_channel_message_does_not_crash_timeout_handler():
    from handlers.message_handlers.guard_set_timeout import guard_set_timeout

    await guard_set_timeout(
        SimpleNamespace(effective_user=None, effective_chat=SimpleNamespace(type="channel"), effective_message=SimpleNamespace(text="hello")),
        SimpleNamespace(),
    )


async def test_delete_continues_after_missing_message():
    from utils.delete_messages import delete_messages

    delete = AsyncMock(side_effect=[BadRequest("Message to delete not found"), None])
    await delete_messages([1, 2], 10, SimpleNamespace(bot=SimpleNamespace(delete_message=delete)), delay=0)
    assert delete.await_count == 2
    assert delete.await_args.kwargs["message_id"] == 2


async def test_nonmatching_block_handler_does_not_stop_dispatch(monkeypatch):
    from handlers import registry

    first = SimpleNamespace(check_update=Mock(return_value=False), block=True, no_parallel=True, callback="first", handle_update=AsyncMock())
    second = SimpleNamespace(check_update=Mock(return_value=True), block=False, no_parallel=True, callback="second", handle_update=AsyncMock())
    monkeypatch.setattr(registry, "iter_message_handlers", lambda: [first, second])
    await registry.message_handler_foreach(None, None)
    first.handle_update.assert_not_awaited()
    second.handle_update.assert_awaited_once()


async def test_unknown_callback_has_readable_feedback():
    from handlers.callback_handlers.callback_handler import callback_handler_func

    query = SimpleNamespace(data="unknown:action", answer=AsyncMock())
    await callback_handler_func(SimpleNamespace(callback_query=query), SimpleNamespace())
    query.answer.assert_awaited_once_with("未知的操作", show_alert=True)
