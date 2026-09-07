"""Group moderation fixtures: isolated database, fake Telegram, no paid services."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import ChatPermissions, Message, User

from models import Group
from registries import engine
from services import group_guard
from services.moderation import rules, store
from services.moderation.schemas import AIConfig
from services.telegram_cache import telegram_cache_manager


@pytest.fixture(autouse=True)
async def reset_guard_state():
    await telegram_cache_manager.reset()
    rules._windows.clear()
    group_guard._settings_cache.clear()
    group_guard._keyword_cache.clear()
    yield
    await telegram_cache_manager.reset()
    rules._windows.clear()
    group_guard._settings_cache.clear()
    group_guard._keyword_cache.clear()


@pytest.fixture
async def guard_group():
    group_id = -1001234567890
    async with engine.new_session() as session:
        session.add(Group(id=group_id))
        await session.commit()
    return group_id


@pytest.fixture
def guard_bot():
    bot = AsyncMock()
    bot.id, bot.defaults = 999, None
    bot.admin_ids = {1, 999}
    bot.rights = dict.fromkeys(
        (
            "can_delete_messages",
            "can_restrict_members",
            "can_invite_users",
            "can_pin_messages",
        ),
        True,
    )

    async def get_member(chat_id, user_id):
        return SimpleNamespace(
            status="administrator" if user_id in bot.admin_ids else "member",
            user=User(user_id, "Member", False),
            **bot.rights,
        )

    bot.get_chat_member.side_effect = get_member

    async def get_administrators(chat_id):
        return [
            SimpleNamespace(user=User(user_id, "Admin", False))
            for user_id in bot.admin_ids
        ]

    bot.get_chat_administrators.side_effect = get_administrators
    bot.get_chat.return_value = SimpleNamespace(
        title="Test group",
        permissions=ChatPermissions(can_send_messages=True, can_send_photos=False),
    )
    bot.send_message.return_value = SimpleNamespace(message_id=888)
    return bot


@pytest.fixture
def guard_message(guard_group, guard_bot):
    def make(**values):
        raw = {
            "message_id": 10,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": guard_group, "type": "supergroup", "title": "Test group"},
            "from": {"id": 2, "first_name": "Member", "is_bot": False},
            "text": "hello",
        }
        raw.update(values)
        return Message.de_json(raw, guard_bot)

    return make


@pytest.fixture
def guard_ai_job(guard_group, guard_message):
    async def make(policy=None, **message_values):
        settings = await store.save_policy(
            guard_group, {"ai_spam": True} | (policy or {})
        )
        # Loopback only: even an accidentally unmocked classifier cannot reach a provider.
        await store.save_ai_config(
            AIConfig(
                base_url="http://127.0.0.1:9/v1",
                text_model="test-text",
                vision_model="test-vision",
            )
        )
        message = guard_message(**message_values)
        version = rules.version(message)
        await store.put_record(
            guard_group,
            "message",
            str(message.message_id),
            {"version": version, "blocked": False},
        )
        return {
            "group_id": guard_group,
            "data": {
                "message": json.loads(message.to_json()),
                "version": version,
                "incident": f"message:{message.message_id}",
                "policy": settings.model_dump(),
            },
        }

    return make
