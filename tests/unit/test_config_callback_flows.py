"""Inline configuration panels: bot, user, and storage callbacks."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from telegram.error import TelegramError

from registries.config_registry import BackBlazeConfig, LocalStorageConfig, TelegramCacheConfig, Token, WebDavConfig
from tests.unit.telegram_fakes import make_context, make_update, sent_texts


def _panel_context():
    context = make_context()
    context.chat_data = {}
    return context


async def test_panel_utils_track_and_close(monkeypatch):
    from handlers.callback_handlers import panel_utils as module

    assert module.build_callback_data("conf:bot:panel:refresh", None) == "conf:bot:panel:refresh"
    assert module.build_callback_data("conf:bot:panel:refresh", 4) == "conf:bot:panel:refresh:4"
    context = _panel_context()
    module.register_panel(context, 9, 4)
    assert module.get_panel_command_message_id(context, 9) == 4
    assert module.get_panel_command_message_id(context, 1) is None
    context.chat_data[module._PANEL_MAP_KEY] = "not-a-dict"
    assert module.get_panel_command_message_id(context, 9) is None
    module.register_panel(context, 9, None)
    module.unregister_panel(context, 9)
    module.unregister_panel(make_context(chat_data={}), 9)
    assert module._parse_command_id(3, context, 9) == 3
    assert module._parse_command_id(None, context, None) is None

    update = make_update(chat_id=5, query_data="close", message_id=9)
    context = _panel_context()
    module.register_panel(context, 9, 4)
    monkeypatch.setattr(module.active_message_handler_registry, "delete", AsyncMock())
    await module.close_panel(update, context, user_id=1, command_message_id=4)
    context.bot.delete_message.assert_awaited()

    context.bot.delete_message = AsyncMock(side_effect=TelegramError("missing"))
    update = make_update(chat_id=5, query_data="close", message_id=9)
    await module.close_panel(update, context, command_message_id=None)
    update.effective_chat = None
    await module.close_panel(update, context)
    update.callback_query = None
    update.effective_message = None
    await module.close_panel(update, context)


@pytest.fixture
def bot_panels(monkeypatch):
    from handlers.callback_handlers.conf_handlers.bot import bot_conf_handler, cache, feature_flags, pixiv, storage

    for module in (bot_conf_handler, cache, feature_flags, pixiv, storage):
        monkeypatch.setattr(module, "refresh_bot_config_panel", AsyncMock(), raising=False)
    monkeypatch.setattr(bot_conf_handler, "has_super_user_access", AsyncMock(return_value=True))
    monkeypatch.setattr(bot_conf_handler, "close_panel", AsyncMock())
    monkeypatch.setattr(cache.config_registry, "get_telegram_cache_config", AsyncMock(return_value=TelegramCacheConfig(backend="redis", ttl_seconds=60, redis_url="redis://localhost/0")))
    monkeypatch.setattr(cache.config_registry, "set_telegram_cache_backend", AsyncMock())
    monkeypatch.setattr(cache.config_registry, "set_telegram_cache_redis_url", AsyncMock())
    monkeypatch.setattr(cache.active_message_handler_registry, "set", AsyncMock())
    monkeypatch.setattr(cache.telegram_cache_manager, "reset", AsyncMock())
    monkeypatch.setattr(storage.config_registry, "get_config", AsyncMock(return_value=" local "))
    monkeypatch.setattr(storage.config_registry, "update_config", AsyncMock())
    monkeypatch.setattr(feature_flags.config_registry, "get_config", AsyncMock(return_value="yes"))
    monkeypatch.setattr(feature_flags.config_registry, "update_config", AsyncMock())
    tokens = [
        Token(token="", enable=False, id=1),
        Token(token="short", enable=True, id=2),
        Token(token="abcdefghijklmnop", enable=False, id=3),
    ]
    monkeypatch.setattr(pixiv.config_registry, "get_pixiv_tokens", AsyncMock(return_value=tokens))
    monkeypatch.setattr(pixiv.config_registry, "set_pixiv_token_enabled", AsyncMock())
    monkeypatch.setattr(pixiv.config_registry, "delete_pixiv_token", AsyncMock())
    monkeypatch.setattr(pixiv.config_registry, "set_all_pixiv_tokens_enabled", AsyncMock())
    monkeypatch.setattr(pixiv.config_registry, "delete_all_pixiv_tokens", AsyncMock())
    monkeypatch.setattr(pixiv.active_message_handler_registry, "set", AsyncMock())
    monkeypatch.setattr(pixiv.pixiv, "read_token_from_config", AsyncMock())
    monkeypatch.setattr(pixiv.pixiv, "token_refresh", AsyncMock())
    pixiv.pixiv.enabled = True
    return bot_conf_handler, cache, feature_flags, pixiv, storage


async def test_bot_conf_dispatch(bot_panels):
    bot_conf, *_rest = bot_panels
    update = make_update(query_data="x")
    await bot_conf.bot_conf_handler_func(update, make_context(), [])
    update.callback_query = None
    await bot_conf.bot_conf_handler_func(update, make_context(), ["panel"])
    update = make_update(query_data="x")
    update.effective_user = None
    await bot_conf.bot_conf_handler_func(update, make_context(), ["panel", "refresh"])

    update = make_update(query_data="x")
    context = make_context()
    await bot_conf.bot_conf_handler_func(update, context, ["panel", "refresh", "12"])
    await bot_conf.bot_conf_handler_func(update, context, ["panel", "refresh", "bad"])
    await bot_conf.bot_conf_handler_func(update, context, ["panel", "close", "4"])
    await bot_conf.bot_conf_handler_func(update, context, ["nope"])
    assert bot_conf._parse_command_message_id(["panel"]) is None
    assert bot_conf._parse_command_message_id(["panel", "refresh", "x"]) is None


async def test_cache_and_storage_and_flags(bot_panels):
    _bot, cache, flags, _pixiv, storage = bot_panels
    update = make_update(query_data="x", user_id=2)
    context = make_context()
    await cache.handle_cache(update, context, [])
    update.callback_query = None
    await cache.handle_cache(update, context, ["menu"])

    update = make_update(query_data="x")
    await cache.handle_cache(update, context, ["menu"])
    await cache.handle_cache(update, context, ["set_backend", "nope"])
    await cache.handle_cache(update, context, ["set_backend", "memory"])
    await cache.handle_cache(update, context, ["set_ttl"])
    await cache.handle_cache(update, context, ["set_redis"])
    await cache.handle_cache(update, context, ["clear_redis"])
    await cache.handle_cache(update, context, ["other"])
    menu = cache._build_menu(TelegramCacheConfig(backend="memory"), command_message_id=None)
    assert menu.inline_keyboard

    await storage.handle_storage(update, context, [])
    await storage.handle_storage(update, context, ["menu"])
    await storage.handle_storage(update, context, ["set", "nope"])
    await storage.handle_storage(update, context, ["set", "WebDAV"])
    await storage.handle_storage(update, context, ["cancel"])
    await storage.handle_storage(update, context, ["other"])
    assert storage._storage_label(None) == "未设置"
    assert storage._storage_label("none") == "未设置"
    assert storage._storage_label("custom") == "custom"
    assert "本地" in storage._storage_label("local")
    storage.config_registry.get_config = AsyncMock(return_value=None)
    await storage.handle_storage(make_update(query_data="x"), context, ["menu"])
    storage.config_registry.get_config = AsyncMock(return_value="   ")
    await storage.handle_storage(make_update(query_data="x"), context, ["menu"])

    await flags.handle_feature_flag(update, context, ["allow_r18g"])
    update.callback_query = None
    await flags.handle_feature_flag(update, context, ["allow_r18g", "on"])
    update = make_update(query_data="x")
    await flags.handle_feature_flag(update, context, ["missing", "on"])
    await flags.handle_feature_flag(update, context, ["allow_r18g", "toggle"])
    await flags.handle_feature_flag(update, context, ["enable_on_new_group", "off"])
    await flags.handle_feature_flag(update, context, ["pixiv_cache_to_telegram", "other"])
    assert flags._is_truthy(True) is True
    assert flags._is_truthy(" off ") is False
    assert flags._is_truthy("maybe") is False
    assert flags._is_truthy(1) is False
    flags.config_registry.get_config = AsyncMock(return_value=False)
    await flags.handle_feature_flag(update, context, ["allow_r18g", "on"])


async def test_pixiv_callback_menu_and_mutations(bot_panels):
    _bot, _cache, _flags, pixiv, _storage = bot_panels
    update = make_update(query_data="x", user_id=2, chat_id=3, message_id=8)
    context = make_context()
    await pixiv.handle_pixiv(update, context, [])
    update.callback_query = None
    await pixiv.handle_pixiv(update, context, ["menu"])

    update = make_update(query_data="x", user_id=2, chat_id=3, message_id=8)
    update.effective_user = None
    await pixiv.handle_pixiv(update, context, ["menu"])

    update = make_update(query_data="x", user_id=2, chat_id=3, message_id=8)
    await pixiv.handle_pixiv(update, context, ["menu"])
    await pixiv.handle_pixiv(update, context, ["add"])
    context.bot.send_message = AsyncMock(return_value=BagMessage())
    await pixiv.handle_pixiv(update, context, ["add"])
    await pixiv.handle_pixiv(update, context, ["token"])
    await pixiv.handle_pixiv(update, context, ["token", "missing"])
    await pixiv.handle_pixiv(update, context, ["token", "2"])
    await pixiv.handle_pixiv(update, context, ["update", "3"])
    await pixiv.handle_pixiv(update, context, ["toggle", "missing"])
    await pixiv.handle_pixiv(update, context, ["toggle", "2"])
    await pixiv.handle_pixiv(update, context, ["delete", "1"])
    pixiv.pixiv.enabled = False
    await pixiv.handle_pixiv(update, context, ["enable_all"])
    pixiv.pixiv.enabled = True
    await pixiv.handle_pixiv(update, context, ["disable_all"])
    await pixiv.handle_pixiv(update, context, ["delete_all"])
    await pixiv.handle_pixiv(update, context, ["nope"])

    disabled = [Token(token="abcdefghijkl", enable=False, id=None)]
    pixiv.config_registry.get_pixiv_tokens = AsyncMock(return_value=disabled)
    await pixiv.handle_pixiv(update, context, ["toggle", "None"])
    enabled_only = [Token(token="abcdefghijkl", enable=True, id=5)]
    pixiv.config_registry.get_pixiv_tokens = AsyncMock(return_value=enabled_only)
    menu = pixiv._build_main_menu(enabled_only, command_message_id=1)
    labels = [button.text for row in menu.inline_keyboard for button in row]
    assert any("禁用全部" in label for label in labels)
    assert pixiv._mask_token_value("   ") == "未设置"
    assert pixiv._mask_token_value("abc") == "abc"
    token_menu = pixiv._build_token_menu(Token(token="x", enable=False, id=5))
    assert token_menu.inline_keyboard


class BagMessage:
    message_id = 0


async def test_user_conf_callbacks(monkeypatch):
    from handlers.callback_handlers.conf_handlers.user_conf_handlers import (
        chat_toggle,
        nick,
        sanity,
        switch_r18g,
        user_conf_handler,
    )

    user = type("User", (), {"id": 1, "sanity_limit": 6, "nick_name": "n", "enable_chat": True, "allow_r18g": False, "status": None})()
    monkeypatch.setattr(user_conf_handler, "refresh_user_config_panel", AsyncMock())
    monkeypatch.setattr(user_conf_handler, "close_panel", AsyncMock())
    monkeypatch.setattr(user_conf_handler.active_message_handler_registry, "delete", AsyncMock())
    monkeypatch.setattr(nick, "refresh_user_config_panel", AsyncMock())
    monkeypatch.setattr(nick.active_message_handler_registry, "set", AsyncMock())
    monkeypatch.setattr(nick.active_message_handler_registry, "delete", AsyncMock())
    monkeypatch.setattr(chat_toggle, "refresh_user_config_panel", AsyncMock())
    monkeypatch.setattr(chat_toggle.user_registry, "set_enable_chat", AsyncMock())
    monkeypatch.setattr(switch_r18g, "refresh_user_config_panel", AsyncMock())
    monkeypatch.setattr(switch_r18g.user_registry, "set_allow_r18g", AsyncMock())
    monkeypatch.setattr(sanity, "refresh_user_config_panel", AsyncMock())
    monkeypatch.setattr(sanity.user_registry, "get_user_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(sanity.user_registry, "set_sanity_limit", AsyncMock())
    panel = type("Panel", (), {"text": "面板", "parse_mode": None})()
    monkeypatch.setattr(sanity.messase_generator, "config_user", AsyncMock(return_value=panel))

    update = make_update(query_data="x")
    context = make_context()
    await user_conf_handler.user_conf_handler_func(update, context, [])
    update.callback_query = None
    await user_conf_handler.user_conf_handler_func(update, context, ["panel", "refresh"])
    update = make_update(query_data="x")
    await user_conf_handler.user_conf_handler_func(update, context, ["panel", "refresh", "6"])
    await user_conf_handler.user_conf_handler_func(update, context, ["panel", "refresh", "bad"])
    await user_conf_handler.user_conf_handler_func(update, context, ["panel", "close"])
    await user_conf_handler.user_conf_handler_func(update, context, ["missing"])
    assert user_conf_handler._parse_command_message_id(["panel"]) is None

    await nick.handle_nick(update, context, [])
    await nick.handle_nick(update, context, ["edit"])
    await nick.handle_nick(update, context, ["cancel"])
    await nick.handle_nick(update, context, ["other"])
    await chat_toggle.handle_chat_toggle(update, context, [])
    await chat_toggle.handle_chat_toggle(update, context, ["maybe"])
    await chat_toggle.handle_chat_toggle(update, context, ["on"])
    await chat_toggle.handle_chat_toggle(update, context, ["off"])
    await switch_r18g.switch_r18g(update, context, [])
    await switch_r18g.switch_r18g(update, context, ["off"])
    await switch_r18g.switch_r18g(update, context, ["on"])
    await switch_r18g.switch_r18g(update, context, ["confirm"])
    await switch_r18g.switch_r18g(update, context, ["cancel"])
    await switch_r18g.switch_r18g(update, context, ["nope"])
    update.callback_query = None
    await switch_r18g._apply(update, context, True)

    await sanity.handle_sanity(update, make_context(), ["edit"])
    update = make_update(query_data="x")
    await sanity.handle_sanity(update, context, [])
    await sanity.handle_sanity(update, context, ["edit"])
    await sanity.handle_sanity(update, context, ["cancel"])
    await sanity.handle_sanity(update, context, ["set", "nope"])
    await sanity.handle_sanity(update, context, ["set", "9"])
    await sanity.handle_sanity(update, context, ["set", "-1"])
    await sanity.handle_sanity(update, context, ["other"])
    assert sanity._chunked((0, 1, 2, 3), 3) == [[0, 1, 2], [3]]


async def test_nickname_and_cache_message_handlers(monkeypatch):
    from handlers.message_handlers import set_backblaze_appid, set_cache_redis, set_cache_ttl, set_user_nickname

    for module, prefix in (
        (set_cache_ttl, "set_cache_ttl"),
        (set_cache_redis, "set_cache_redis"),
        (set_backblaze_appid, "set_backblaze_appid"),
    ):
        monkeypatch.setattr(module, "has_super_user_access", AsyncMock(return_value=True))
        monkeypatch.setattr(module, "refresh_bot_config_panel", AsyncMock())
        monkeypatch.setattr(module.active_message_handler_registry, "delete", AsyncMock())

    monkeypatch.setattr(set_cache_ttl.config_registry, "set_telegram_cache_ttl", AsyncMock())
    monkeypatch.setattr(set_cache_ttl.telegram_cache_manager, "reset", AsyncMock())
    monkeypatch.setattr(set_cache_redis.config_registry, "set_telegram_cache_redis_url", AsyncMock())
    monkeypatch.setattr(set_cache_redis.telegram_cache_manager, "reset", AsyncMock())
    monkeypatch.setattr(set_backblaze_appid.config_registry, "update_config", AsyncMock())
    monkeypatch.setattr(set_user_nickname, "refresh_user_config_panel", AsyncMock())
    monkeypatch.setattr(set_user_nickname.user_registry, "set_nick_name", AsyncMock())
    monkeypatch.setattr(set_user_nickname.active_message_handler_registry, "delete", AsyncMock())

    async def submit(module, func, text, key, chat_type="private"):
        monkeypatch.setattr(module.active_message_handler_registry, "get", AsyncMock(return_value=key))
        update = make_update(text=text, chat_type=chat_type, user_id=2)
        context = make_context()
        await getattr(module, func)(update, context)
        return update, context

    update = make_update(text=None)
    await set_cache_ttl.set_cache_ttl(update, make_context())
    monkeypatch.setattr(set_cache_ttl.active_message_handler_registry, "get", AsyncMock(return_value=None))
    await set_cache_ttl.set_cache_ttl(make_update(text="40"), make_context())
    monkeypatch.setattr(set_cache_ttl, "has_super_user_access", AsyncMock(return_value=False))
    await submit(set_cache_ttl, "set_cache_ttl", "40", "set_cache_ttl:8", chat_type="group")
    monkeypatch.setattr(set_cache_ttl, "has_super_user_access", AsyncMock(return_value=True))
    await submit(set_cache_ttl, "set_cache_ttl", "40", "set_cache_ttl:bad")
    context = make_context()
    context.bot.delete_message = AsyncMock(side_effect=TelegramError("gone"))
    monkeypatch.setattr(set_cache_ttl.active_message_handler_registry, "get", AsyncMock(return_value="set_cache_ttl:8"))
    await set_cache_ttl.set_cache_ttl(make_update(text="nope", chat_type="private"), context)
    await submit(set_cache_ttl, "set_cache_ttl", "10", "set_cache_ttl:8")
    _update, context = await submit(set_cache_ttl, "set_cache_ttl", "45", "set_cache_ttl:8")
    assert any("45" in text for text in sent_texts(context.bot.send_message))

    await submit(set_cache_redis, "set_cache_redis", "-", "set_cache_redis:8")
    _update, context = await submit(set_cache_redis, "set_cache_redis", "redis://localhost", "set_cache_redis:8")
    assert any("Redis" in text for text in sent_texts(context.bot.send_message))
    await submit(set_cache_redis, "set_cache_redis", "redis://localhost", "set_cache_redis:")

    monkeypatch.setattr(set_backblaze_appid.config_registry, "update_config", AsyncMock(side_effect=RuntimeError("db")))
    await submit(set_backblaze_appid, "set_backblaze_appid", "app", "set_backblaze_appid:8")
    monkeypatch.setattr(set_backblaze_appid.config_registry, "update_config", AsyncMock())
    context = make_context()
    context.bot.delete_message = AsyncMock(side_effect=TelegramError("gone"))
    monkeypatch.setattr(set_backblaze_appid.active_message_handler_registry, "get", AsyncMock(return_value="set_backblaze_appid:bad"))
    await set_backblaze_appid.set_backblaze_appid(make_update(text="app"), context)
    monkeypatch.setattr(set_backblaze_appid.active_message_handler_registry, "get", AsyncMock(return_value="set_backblaze_appid"))
    await set_backblaze_appid.set_backblaze_appid(make_update(text="app"), make_context())
    _update, context = await submit(set_backblaze_appid, "set_backblaze_appid", "app", "set_backblaze_appid:8")
    assert any("updated" in text.lower() for text in sent_texts(context.bot.send_message))

    await set_user_nickname.set_user_nickname(make_update(text=None), make_context())
    monkeypatch.setattr(set_user_nickname.active_message_handler_registry, "get", AsyncMock(return_value="other"))
    await set_user_nickname.set_user_nickname(make_update(text="n"), make_context())
    await submit(set_user_nickname, "set_user_nickname", "n", "set_user_nickname:")
    await submit(set_user_nickname, "set_user_nickname", "n", "set_user_nickname:bad")
    await submit(set_user_nickname, "set_user_nickname", "-", "set_user_nickname:8")
    _update, context = await submit(set_user_nickname, "set_user_nickname", "新昵称", "set_user_nickname:8")
    assert any("昵称" in text for text in sent_texts(context.bot.send_message))


def test_storage_dataclasses_normalize():
    blaze = BackBlazeConfig(base_path="\\a\\b\\", base_url="https://cdn.example/")
    assert blaze.base_path == "a/b"
    assert blaze.base_url == "https://cdn.example"
    webdav = WebDavConfig(endpoint=" https://dav ", base_path="", public_base_url="https://pub/")
    assert webdav.endpoint == "https://dav"
    local = LocalStorageConfig(root_path=" storage ", base_url="https://files/")
    assert local.root_path == "storage"
    assert local.base_url == "https://files"
