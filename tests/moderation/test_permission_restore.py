"""Permission restoration must tolerate extra fields in Telegram responses."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from telegram import Chat, ChatPermissions, User

from models import GroupGuardPendingVerification as Pending
from models import GuardEvent
from registries import engine
from services.moderation import actions, store, verification
from services.moderation.schemas import ActionRequest, Policy


@pytest.mark.parametrize("route", ["verification", "unmute"])
async def test_restore_ignores_legacy_and_unknown_api_permissions(
    route, guard_group, guard_bot
):
    guard_bot.get_chat.return_value.permissions = ChatPermissions.de_json(
        {
            "can_send_messages": True,
            "can_send_photos": False,
            "can_send_audios": True,
            "can_send_media_messages": True,
            "can_future_permission": True,
        },
        guard_bot,
    )
    if route == "verification":
        user = User(2, "New", False)
        await verification.start(guard_bot, guard_group, user, "Group", Policy())
        async with engine.new_session() as session:
            token = (await session.get(Pending, (guard_group, 2))).token
        query = SimpleNamespace(answer=AsyncMock())
        await verification.callback(
            SimpleNamespace(
                callback_query=query,
                effective_chat=Chat(guard_group, "supergroup"),
                effective_user=user,
            ),
            SimpleNamespace(bot=guard_bot),
            ["verify", token],
        )
        query.answer.assert_awaited_once_with()
        guard_bot.send_message.assert_awaited_with(guard_group, "验证通过")
        async with engine.new_session() as session:
            row = await session.get(Pending, (guard_group, 2))
            assert row.state == "passed"
            assert row.completed_at is not None
            event = await session.scalar(
                select(GuardEvent).where(GuardEvent.incident == token)
            )
            assert event.status == "passed"
    else:
        for action in ("mute", "unmute"):
            result = await actions.execute(
                guard_bot,
                guard_group,
                ActionRequest(action=action, user_id=2, request_id=action),
                actor_id=1,
            )
            assert result["status"] == "success"
        assert await store.record(guard_group, "restriction", "2") is None

    assert guard_bot.restrict_chat_member.await_count == 2
    call = guard_bot.restrict_chat_member.call_args
    assert call.args[2].to_dict() == {
        "can_send_messages": True,
        "can_send_photos": False,
        "can_send_audios": True,
    }
    assert call.kwargs["use_independent_chat_permissions"] is True


@pytest.mark.parametrize("defaults", [None, {}, {"can_send_media_messages": True}])
async def test_missing_supported_defaults_never_grants_permissions(
    defaults, guard_group, guard_bot
):
    guard_bot.get_chat.return_value.permissions = (
        ChatPermissions.de_json(defaults, None) if defaults is not None else None
    )
    await actions.restore_permissions(guard_bot, guard_group, 2, {})
    assert not any(guard_bot.restrict_chat_member.call_args.args[2].to_dict().values())


async def test_restore_preserves_individual_restrictions_and_deadline(
    guard_group, guard_bot
):
    guard_bot.get_chat.return_value.permissions = ChatPermissions.de_json(
        {
            "can_send_messages": True,
            "can_send_photos": False,
            "can_send_audios": True,
            "can_send_media_messages": True,
        },
        None,
    )
    deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    await actions.restore_permissions(
        guard_bot,
        guard_group,
        2,
        {
            "permissions": {
                "can_send_messages": True,
                "can_send_photos": True,
                "can_send_audios": False,
            },
            "until": deadline.isoformat(),
        },
    )
    call = guard_bot.restrict_chat_member.call_args
    assert call.args[2].to_dict() == {
        "can_send_messages": True,
        "can_send_photos": False,
        "can_send_audios": False,
    }
    assert call.kwargs["until_date"] == deadline
