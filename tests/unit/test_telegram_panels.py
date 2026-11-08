"""Panel builders declare a parse mode and escape only when that mode needs it."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from defines import UserStatus
from messase_generator.bot_admin import bot_admin
from messase_generator.config_group import config_group
from messase_generator.config_user import config_user
from models import Group, User
from registries.config_registry import (
    BackBlazeConfig,
    LocalStorageConfig,
    TelegramCacheConfig,
    WebDavConfig,
)
from services.group_guard import GuardSettings
from utils.telegram_text import PARSE_MODE_MARKDOWN_V2

from tests.unit.telegram_markup import assert_markdown_v2_escaped


async def test_bot_admin_escapes_dynamic_text_for_markdown_v2(monkeypatch):
    import importlib

    module = importlib.import_module("messase_generator.bot_admin")

    async def get_config(key):
        return {
            "allow_r18g": "false",
            "enable_on_new_group": "false",
            "pixiv_cache_to_telegram": "true",
            "storage_service_use": "my_backend.v2",
        }.get(key)

    monkeypatch.setattr(module.config_registry, "get_config", get_config)
    monkeypatch.setattr(module.config_registry, "get_backblaze_config", AsyncMock(return_value=BackBlazeConfig()))
    monkeypatch.setattr(module.config_registry, "get_webdav_config", AsyncMock(return_value=WebDavConfig()))
    monkeypatch.setattr(
        module.config_registry,
        "get_local_storage_config",
        AsyncMock(return_value=LocalStorageConfig(root_path="/data")),
    )
    monkeypatch.setattr(module.config_registry, "get_pixiv_tokens", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        module.config_registry,
        "get_telegram_cache_config",
        AsyncMock(
            return_value=TelegramCacheConfig(
                backend="redis",
                ttl_seconds=300,
                redis_url="redis://cache.example.com/0_db",
            )
        ),
    )

    panel = await bot_admin()

    assert panel.parse_mode == PARSE_MODE_MARKDOWN_V2
    assert_markdown_v2_escaped(panel.text)
    assert "my_backend.v2" not in panel.text
    assert r"my\_backend\.v2" in panel.text
    assert "redis://cache.example.com/0_db" not in panel.text
    assert r"redis://cache\.example\.com/0\_db" in panel.text


async def test_user_and_group_panels_keep_special_characters_as_plain_text(monkeypatch):
    import importlib

    group_module = importlib.import_module("messase_generator.config_group")

    nick = "nick_*[`]<b>&"
    user = User(
        id=7,
        nick_name=nick,
        enable_chat=False,
        sanity_limit=5,
        allow_r18g=False,
        status=UserStatus.NORMAL,
    )
    user_panel = await config_user(user=user)
    assert user_panel.parse_mode is None
    assert nick in user_panel.text
    assert "&amp;" not in user_panel.text

    group_name = "group_*[`]<b>&"
    monkeypatch.setattr(
        group_module.group_guard,
        "get_guard_settings",
        AsyncMock(
            return_value=GuardSettings(
                group_id=5,
                verification_enabled=False,
                verification_timeout=60,
                verification_message="msg_*[`]",
                keyword_filter_enabled=False,
                kick_on_timeout=True,
            )
        ),
    )
    monkeypatch.setattr(group_module.group_guard, "list_keyword_rules", AsyncMock(return_value=[]))
    group = Group(
        id=5,
        name=group_name,
        enable=True,
        allow_setu=True,
        sanity_limit=6,
        allow_r18g=False,
    )
    group_panel = await config_group(group=group)
    assert group_panel.parse_mode is None
    assert group_name in group_panel.text
    assert "&amp;" not in group_panel.text


def _context(edit):
    return SimpleNamespace(
        bot=SimpleNamespace(edit_message_text=edit, edit_message_reply_markup=AsyncMock()),
        chat_data={},
    )


async def test_panel_refresh_forwards_the_declared_parse_mode(monkeypatch):
    from handlers.callback_handlers.conf_handlers.bot import panel as bot_panel
    from handlers.callback_handlers.conf_handlers.group_conf_handlers import panel as group_panel
    from handlers.callback_handlers.conf_handlers.user_conf_handlers import panel as user_panel
    from messase_generator.bot_admin import BotAdmin
    from messase_generator.config_group import ConfigGroup
    from messase_generator.config_user import ConfigUser

    bot_edit = AsyncMock()
    monkeypatch.setattr(
        bot_panel.messase_generator,
        "bot_admin",
        AsyncMock(return_value=BotAdmin(text=r"my\_backend\.v2", keyboard=[], parse_mode="MarkdownV2")),
    )
    await bot_panel.refresh_bot_config_panel(_context(bot_edit), chat_id=1, message_id=2, command_message_id=3)
    assert bot_edit.await_args.kwargs["parse_mode"] == "MarkdownV2"
    assert bot_edit.await_args.kwargs["text"] == r"my\_backend\.v2"

    user_edit = AsyncMock()
    monkeypatch.setattr(user_panel.user_registry, "get_user_by_id", AsyncMock(return_value=SimpleNamespace(id=7)))
    monkeypatch.setattr(
        user_panel.messase_generator,
        "config_user",
        AsyncMock(return_value=ConfigUser(text="nick_*[`]<b>&", keyboard=[], parse_mode=None)),
    )
    await user_panel.refresh_user_config_panel(_context(user_edit), chat_id=1, message_id=2, user_id=7)
    assert "parse_mode" not in user_edit.await_args.kwargs
    assert user_edit.await_args.kwargs["text"] == "nick_*[`]<b>&"

    group_edit = AsyncMock()
    monkeypatch.setattr(group_panel.group_registry, "get_group_by_id", AsyncMock(return_value=SimpleNamespace(id=5)))
    monkeypatch.setattr(
        group_panel.messase_generator,
        "config_group",
        AsyncMock(return_value=ConfigGroup(text="group_*[`]<b>&", keyboard=[], parse_mode=None)),
    )
    await group_panel.refresh_group_config_panel(
        _context(group_edit), chat_id=1, message_id=2, group_id=5
    )
    assert "parse_mode" not in group_edit.await_args.kwargs
    assert group_edit.await_args.kwargs["text"] == "group_*[`]<b>&"
