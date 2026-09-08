"""Telegram permission boundaries, commands and review/verification callbacks."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from telegram import Chat, Update, User
from telegram.error import BadRequest, RetryAfter

from handlers.command_handlers import moderation_handler as commands
from models import GroupGuardPendingVerification as Pending
from models import GuardEvent
from registries import engine
from services.moderation import actions, reviews, rules, runtime, store, verification
from services.moderation.schemas import ActionRequest, Policy, Rule


@pytest.mark.parametrize(
    "identity", ["administrator", "creator", "self", "anonymous", "exempt", "unknown"]
)
async def test_automatic_moderation_respects_identity_boundaries(
    identity, guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"rules_enabled": True, "flood_enabled": True})
    await store.put_record(
        guard_group, "rule", "spam", Rule(kind="keyword", pattern="spam").model_dump()
    )
    values = {"text": "spam"}
    if identity == "administrator" or identity == "creator":
        guard_bot.admin_ids.add(2)
    elif identity == "self":
        values["from"] = {"id": guard_bot.id, "first_name": "Bot", "is_bot": True}
    elif identity == "anonymous":
        values["sender_chat"] = {"id": guard_group, "type": "supergroup"}
    elif identity == "exempt":
        await store.put_record(guard_group, "exempt", "2", {})
    else:
        guard_bot.get_chat_administrators.side_effect = BadRequest(
            "cannot determine role"
        )
    for index in range(7):
        await runtime.preprocess(
            Update(index, message=guard_message(message_id=10 + index, **values)),
            SimpleNamespace(bot=guard_bot),
        )
    guard_bot.delete_message.assert_not_awaited()
    guard_bot.restrict_chat_member.assert_not_awaited()
    assert await store.warnings(guard_group, 2) == []


async def test_disabled_moderation_skips_admin_lookup_and_message_tracking(
    guard_group, guard_bot, guard_message
):
    await runtime.preprocess(
        Update(1, message=guard_message()), SimpleNamespace(bot=guard_bot)
    )
    guard_bot.get_chat_member.assert_not_awaited()
    guard_bot.get_chat_administrators.assert_not_awaited()
    assert await store.record(guard_group, "message", "10") is None


async def test_enabled_moderation_reuses_cached_admin_list(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"rules_enabled": True})
    for index in range(2):
        await runtime.preprocess(
            Update(
                index,
                message=guard_message(message_id=10 + index, text="ordinary"),
            ),
            SimpleNamespace(bot=guard_bot),
        )
    guard_bot.get_chat_member.assert_not_awaited()
    guard_bot.get_chat_administrators.assert_awaited_once_with(guard_group)


async def test_failed_admin_lookup_is_negatively_cached(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"rules_enabled": True})
    guard_bot.get_chat_administrators.side_effect = BadRequest("unavailable")
    for index in range(2):
        await runtime.preprocess(
            Update(index, message=guard_message(message_id=10 + index)),
            SimpleNamespace(bot=guard_bot),
        )
    guard_bot.get_chat_administrators.assert_awaited_once_with(guard_group)
    guard_bot.delete_message.assert_not_awaited()


async def test_failed_admin_lookup_still_records_edited_version(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"rules_enabled": True})
    original = guard_message(text="old")
    await store.put_record(
        guard_group,
        "message",
        str(original.message_id),
        {
            "version": rules.version(original),
            "timestamp": original.date.timestamp(),
        },
    )
    guard_bot.get_chat_administrators.side_effect = BadRequest("unavailable")
    edited = guard_message(
        text="new",
        edit_date=int(original.date.timestamp()) + 1,
    )

    await runtime.preprocess(
        Update(3, edited_message=edited), SimpleNamespace(bot=guard_bot)
    )

    saved = await store.record(guard_group, "message", str(original.message_id))
    assert saved["data"]["version"] == rules.version(edited)
    guard_bot.delete_message.assert_not_awaited()


@pytest.mark.parametrize(
    "action,right,method,target",
    [
        ("mute", "can_restrict_members", "restrict_chat_member", {"user_id": 2}),
        ("delete", "can_delete_messages", "delete_message", {"message_id": 10}),
        ("pin", "can_pin_messages", "pin_chat_message", {"message_id": 10}),
    ],
)
async def test_each_action_requires_its_telegram_right(
    action, right, method, target, guard_group, guard_bot
):
    guard_bot.rights[right] = False
    result = await actions.execute(
        guard_bot,
        guard_group,
        ActionRequest(action=action, request_id="right-check", **target),
        actor_id=1,
    )
    assert result["status"] == "failed"
    assert right in result["data"]["error"]
    getattr(guard_bot, method).assert_not_awaited()


@pytest.mark.parametrize(
    "reply,args,seconds",
    [
        (False, ["2", "30m", "spam"], 1800),
        (True, ["2h", "spam"], 7200),
        (True, ["1d"], 86400),
    ],
)
async def test_mute_command_target_duration_and_update_deduplication(
    reply, args, seconds, guard_group, guard_bot, guard_message
):
    target = guard_message().to_dict() if reply else None
    message = guard_message(
        text="/mute@ExampleBot",
        reply_to_message=target,
        **{"from": {"id": 1, "first_name": "Admin", "is_bot": False}},
    )
    update = Update(72, message=message)
    before = store.now()
    for _ in range(2):
        await commands.moderation_command(
            update, SimpleNamespace(bot=guard_bot, args=args)
        )
    restriction = (await store.record(guard_group, "restriction", "2"))["data"]
    deadline = datetime.fromisoformat(restriction["deadline"])
    assert (
        before + timedelta(seconds=seconds)
        <= deadline
        <= store.now() + timedelta(seconds=seconds)
    )
    guard_bot.restrict_chat_member.assert_awaited_once()
    assert all(
        "success" in call.kwargs["text"]
        for call in guard_bot.send_message.await_args_list
    )


@pytest.mark.parametrize("case", ["cross_group", "revoked_admin"])
async def test_settings_callback_rechecks_group_and_admin(case, guard_group, guard_bot):
    query = AsyncMock()
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=Chat(guard_group, "supergroup"),
        effective_user=User(1, "Admin", False),
    )
    target_group = guard_group
    if case == "cross_group":
        target_group += 1
    else:
        guard_bot.admin_ids.remove(1)
    await commands.callback(
        update,
        SimpleNamespace(bot=guard_bot),
        ["toggle", str(target_group), "flood_enabled"],
    )
    assert not (await store.policy(guard_group)).flood_enabled
    assert not (await store.policy(target_group)).flood_enabled
    assert query.answer.call_args.kwargs["show_alert"] is True
    query.message.edit_text.assert_not_awaited()


async def test_verification_cannot_be_completed_by_another_member(
    guard_group, guard_bot
):
    await verification.start(
        guard_bot, guard_group, User(2, "New", False), "Group", Policy()
    )
    async with engine.new_session() as session:
        token = (await session.get(Pending, (guard_group, 2))).token
    query = AsyncMock()
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=Chat(guard_group, "supergroup"),
        effective_user=User(3, "Other", False),
    )
    await verification.callback(
        update, SimpleNamespace(bot=guard_bot), ["verify", token]
    )
    assert query.answer.call_args.kwargs["show_alert"] is True
    assert guard_bot.restrict_chat_member.await_count == 1
    async with engine.new_session() as session:
        assert (await session.get(Pending, (guard_group, 2))).state == "pending"


async def test_failed_verification_restore_never_reports_passed(guard_group, guard_bot):
    await verification.start(
        guard_bot, guard_group, User(2, "New", False), "Group", Policy()
    )
    async with engine.new_session() as session:
        token = (await session.get(Pending, (guard_group, 2))).token
    guard_bot.restrict_chat_member.side_effect = BadRequest("permission revoked")
    result = await verification.finish(guard_bot, guard_group, 2, token)
    assert "验证通过" not in result
    async with engine.new_session() as session:
        assert (await session.get(Pending, (guard_group, 2))).state == "uncertain"


async def test_repeated_join_does_not_replace_unresolved_verification(
    guard_group, guard_bot
):
    user = User(2, "New", False)
    await verification.start(guard_bot, guard_group, user, "Group", Policy())
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        token = row.token
        row.state = "uncertain"
        await session.commit()
    guard_bot.restrict_chat_member.reset_mock()

    await verification.start(guard_bot, guard_group, user, "Group", Policy())

    guard_bot.restrict_chat_member.assert_not_awaited()
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        assert row.token == token and row.state == "uncertain"


async def test_join_requests_remain_disabled_by_default(guard_group, guard_bot):
    update = SimpleNamespace(
        chat_join_request=SimpleNamespace(chat=Chat(guard_group, "supergroup"))
    )
    await verification.join_request(update, SimpleNamespace(bot=guard_bot))
    guard_bot.approve_chat_join_request.assert_not_awaited()
    guard_bot.decline_chat_join_request.assert_not_awaited()
    assert await store.records(guard_group, "review") == []


async def test_join_auto_approval_permission_failure_falls_back_to_review(
    guard_group, guard_bot
):
    await store.save_policy(
        guard_group,
        {"join_requests_enabled": True, "join_auto_approve": True},
    )
    guard_bot.rights["can_invite_users"] = False
    request = SimpleNamespace(
        chat=Chat(guard_group, "supergroup"),
        from_user=User(2, "Applicant", False),
        date=datetime.now(timezone.utc),
    )
    update = SimpleNamespace(chat_join_request=request)
    context = SimpleNamespace(bot=guard_bot)

    await verification.join_request(update, context)
    await verification.join_request(update, context)

    guard_bot.approve_chat_join_request.assert_not_awaited()
    review_rows = await store.records(guard_group, "review")
    assert len(review_rows) == 1 and review_rows[0]["data"]["state"] == "pending"
    async with engine.new_session() as session:
        receipt = await session.scalar(
            select(GuardEvent).where(GuardEvent.action == "join_request")
        )
    assert receipt.status == "success"
    assert receipt.data["review"] is True


async def test_join_auto_approval_bad_request_is_definitive_failure(
    guard_group, guard_bot
):
    await store.save_policy(
        guard_group,
        {"join_requests_enabled": True, "join_auto_approve": True},
    )
    guard_bot.approve_chat_join_request.side_effect = BadRequest("request expired")
    request = SimpleNamespace(
        chat=Chat(guard_group, "supergroup"),
        from_user=User(2, "Applicant", False),
        date=datetime.now(timezone.utc),
    )

    await verification.join_request(
        SimpleNamespace(chat_join_request=request), SimpleNamespace(bot=guard_bot)
    )

    async with engine.new_session() as session:
        receipt = await session.scalar(
            select(GuardEvent).where(
                GuardEvent.group_id == guard_group,
                GuardEvent.action == "join_request",
            )
        )
    assert receipt.status == "failed"


async def test_report_rate_limit_and_message_deduplication(
    guard_group, guard_bot, guard_message
):
    for index, target in enumerate([10, 10, 11, 12]):
        reply = guard_message(message_id=target).to_dict()
        message = guard_message(
            message_id=50 + index, text="/report", reply_to_message=reply
        )
        await commands.moderation_command(
            Update(index, message=message), SimpleNamespace(bot=guard_bot, args=[])
        )
    records = await store.records(guard_group, "review")
    assert {r["data"]["message_id"] for r in records} == {10, 11}
    assert "过于频繁" in guard_bot.send_message.call_args.kwargs["text"]
    guard_bot.delete_message.assert_not_awaited()


async def test_review_concurrency_executes_one_punishment(guard_group, guard_bot):
    row = await reviews.create(
        guard_group, "report:10", {"kind": "message", "user_id": 2, "message_id": 10}
    )
    results = await asyncio.gather(
        *[
            reviews.decide(
                guard_bot, guard_group, row["id"], "punish", "spam", actor_id=1
            )
            for _ in range(2)
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    guard_bot.delete_message.assert_awaited_once_with(guard_group, 10)
    assert len(await store.warnings(guard_group, 2)) == 1


async def test_edited_message_review_does_not_punish_new_content(
    guard_group, guard_bot
):
    row = await reviews.create(
        guard_group,
        "report:10",
        {"kind": "message", "user_id": 2, "message_id": 10, "version": "old"},
    )
    await store.put_record(guard_group, "message", "10", {"version": "new"})
    result = await reviews.decide(
        guard_bot, guard_group, row["id"], "punish", "spam", actor_id=1
    )
    assert result["data"]["state"] == "failed"
    guard_bot.delete_message.assert_not_awaited()
    assert await store.warnings(guard_group, 2) == []


async def test_rate_limited_purge_records_each_actual_deletion(
    guard_group, guard_bot, monkeypatch
):
    monkeypatch.setenv("PTB_TIMEDELTA", "1")
    guard_bot.delete_message.side_effect = [True, RetryAfter(2), True]
    result = await actions.execute(
        guard_bot,
        guard_group,
        ActionRequest(
            action="purge",
            message_id=10,
            end_message_id=12,
            request_id="purge",
        ),
        actor_id=1,
    )
    assert result["status"] == "partial"
    assert result["data"] == {
        "deleted": [10],
        "failed": [11],
        "unattempted": [12],
        "retry_after": 2,
    }
    assert guard_bot.delete_message.await_count == 2
