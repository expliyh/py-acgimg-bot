"""Tests for the administrator manual verification command."""

from types import SimpleNamespace

import pytest
from telegram import Update, User

from handlers.command_handlers import verification_handler
from models import GroupGuardPendingVerification as Pending
from registries import engine, user_registry
from services.moderation import store, verification


def _admin_message(guard_message, text="/verify 2", **values):
    return guard_message(
        text=text,
        **{"from": {"id": 1, "first_name": "Admin", "is_bot": False}, **values},
    )


async def test_verify_command_retriggers_when_group_verification_is_disabled(
    guard_group, guard_bot, guard_message
):
    await user_registry.sync_telegram_user(2, "Member")
    guard_bot.members[2] = SimpleNamespace(
        status="member", user=User(2, "Member", False, username="Member")
    )

    message = _admin_message(guard_message, "/verify @member")
    await verification_handler.verify_command(
        Update(100, message=message),
        SimpleNamespace(bot=guard_bot, args=["@member"]),
    )

    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
    assert row is not None and row.state == "pending"
    assert guard_bot.restrict_chat_member.await_count == 1
    texts = [call.kwargs.get("text", "") for call in guard_bot.send_message.await_args_list]
    texts.extend(call.args[1] for call in guard_bot.send_message.await_args_list if len(call.args) > 1)
    assert any("重新发起入群验证" in text for text in texts)


async def test_verify_command_replaces_existing_pending_prompt(
    guard_group, guard_bot
):
    member = User(2, "Member", False, username="member")
    settings = await store.policy(guard_group)
    await verification.start(guard_bot, guard_group, member, "Group", settings)
    async with engine.new_session() as session:
        old = await session.get(Pending, (guard_group, 2))
        old_token = old.token

    result = await verification.retrigger(
        guard_bot,
        guard_group,
        member,
        "Group",
        settings,
        actor_id=1,
        request_id="manual-1",
    )

    assert result.state == "pending" and result.replaced
    assert result.token != old_token
    guard_bot.delete_message.assert_awaited_once_with(guard_group, 888)
    assert await verification.finish(guard_bot, guard_group, 2, old_token) == "验证已失效或已处理"
    duplicate = await verification.retrigger(
        guard_bot,
        guard_group,
        member,
        "Group",
        settings,
        actor_id=1,
        request_id="manual-1",
    )
    assert duplicate.token == result.token
    assert guard_bot.restrict_chat_member.await_count == 2


async def test_verify_command_rejects_uncertain_existing_verification(
    guard_group, guard_bot
):
    member = User(2, "Member", False)
    await verification.start(guard_bot, guard_group, member, "Group", await store.policy(guard_group))
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        row.state = "uncertain"
        await session.commit()

    with pytest.raises(ValueError, match="无法安全重新触发"):
        await verification.retrigger(
            guard_bot,
            guard_group,
            member,
            "Group",
            await store.policy(guard_group),
            actor_id=1,
            request_id="manual-uncertain",
        )


async def test_verify_command_requires_group_admin(guard_group, guard_bot, guard_message):
    guard_bot.admin_ids.remove(1)
    message = _admin_message(guard_message, "/verify 2")

    await verification_handler.verify_command(
        Update(101, message=message),
        SimpleNamespace(bot=guard_bot, args=["2"]),
    )

    guard_bot.restrict_chat_member.assert_not_awaited()
