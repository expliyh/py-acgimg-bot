"""Tests for the administrator manual verification command."""

from types import SimpleNamespace

import pytest
from telegram import Update, User

from handlers.command_handlers import verification_handler
from models import GroupGuardPendingVerification as Pending
from registries import engine, user_registry
from services.moderation import store, verification
from services.moderation.schemas import ActionRequest


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


@pytest.mark.parametrize("legacy", [False, True])
async def test_retrigger_after_timeout_restores_permissions(guard_group, guard_bot, legacy):
    from datetime import timedelta

    settings = await store.save_policy(guard_group, {"kick_on_timeout": False})
    member = User(2, "Member", False)
    await verification.start(guard_bot, guard_group, member, "Group", settings)
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        row.expires_at = store.now() - timedelta(seconds=1)
        token = row.token
        await session.commit()
    assert await verification.finish(guard_bot, guard_group, 2, token, expired=True) == "验证超时，保持限制发言"
    if legacy:
        restriction = await store.record(guard_group, "restriction", "2")
        restriction["data"].pop("source")
        await store.put_record(guard_group, "restriction", "2", restriction["data"])
    result = await verification.retrigger(
        guard_bot, guard_group, member, "Group", settings, actor_id=1, request_id="retry-timeout",
    )
    assert await verification.finish(guard_bot, guard_group, 2, result.token) == "验证通过"
    assert guard_bot.restrict_chat_member.call_args.args[2].can_send_messages is True
    assert await store.record(guard_group, "restriction", "2") is None


async def test_retrigger_preserves_administrator_mute(guard_group, guard_bot):
    from services.moderation import actions

    settings = await store.policy(guard_group)
    member = User(2, "Member", False)
    await verification.start(guard_bot, guard_group, member, "Group", settings)
    result = await actions.execute(
        guard_bot, guard_group, ActionRequest(action="mute", user_id=2, duration=300, request_id="admin-mute"), actor_id=1,
    )
    assert result["status"] == "success"
    retriggered = await verification.retrigger(
        guard_bot, guard_group, member, "Group", settings, actor_id=1, request_id="retry-muted",
    )
    before = guard_bot.restrict_chat_member.await_count
    assert await verification.finish(guard_bot, guard_group, 2, retriggered.token) == "验证通过"
    assert guard_bot.restrict_chat_member.await_count == before
    restriction = await store.record(guard_group, "restriction", "2")
    assert restriction["data"]["event_id"] == result["id"]
    assert restriction["data"]["deadline"]


async def test_timeout_restriction_survives_failed_restoration(guard_group, guard_bot):
    from datetime import timedelta
    from telegram.error import BadRequest

    settings = await store.save_policy(guard_group, {"kick_on_timeout": False})
    member = User(2, "Member", False)
    await verification.start(guard_bot, guard_group, member, "Group", settings)
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        token = row.token
        row.expires_at = store.now() - timedelta(seconds=1)
        await session.commit()
    await verification.finish(guard_bot, guard_group, 2, token, expired=True)
    result = await verification.retrigger(
        guard_bot, guard_group, member, "Group", settings, actor_id=1, request_id="retry-fails",
    )
    guard_bot.restrict_chat_member.side_effect = BadRequest("cannot restore")
    assert "操作失败" in await verification.finish(guard_bot, guard_group, 2, result.token)
    assert await store.record(guard_group, "restriction", "2") is not None
    guard_bot.restrict_chat_member.side_effect = None
    result = await verification.retrigger(
        guard_bot, guard_group, member, "Group", settings, actor_id=1, request_id="retry-recovers",
    )
    assert await verification.finish(guard_bot, guard_group, 2, result.token) == "验证通过"
    assert await store.record(guard_group, "restriction", "2") is None
