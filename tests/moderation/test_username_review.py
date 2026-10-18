import asyncio
from types import SimpleNamespace
from datetime import timedelta

import pytest
from telegram import Update
from telegram.error import BadRequest

from services.moderation import runtime, store, worker, verification, username_review
from services.moderation.schemas import AIConfig, UsernameReviewConfig, UsernameVerdict
from unittest.mock import AsyncMock
from services.moderation.username_review import REMOVAL_NOTICE
from models import GuardTask
from registries import engine
from sqlalchemy import select

from services.moderation.username_review import inspect_user


def policy(**overrides):
    values = {
        "username_review_enabled": True,
        "username_sensitive_words": [],
        "username_block_emoji": False,
        "username_block_abnormal_chars": False,
        "username_ai_check": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def user(username=None, full_name="普通用户"):
    return SimpleNamespace(username=username, full_name=full_name)


def test_sensitive_username_is_rejected_case_insensitively():
    hit = inspect_user(user("ScAm_Admin"), policy(username_sensitive_words=["scam"]))
    assert hit and hit["kind"] == "sensitive_word"


@pytest.mark.parametrize("value", ["USDT", "usdt", "UsDt", "ＵｓＤｔ"])
@pytest.mark.parametrize("field", ["username", "full_name"])
@pytest.mark.parametrize("global_word", [False, True])
def test_sensitive_words_ignore_case_for_both_sources_and_name_fields(value, field, global_word):
    settings = policy(username_sensitive_words=[] if global_word else ["usdt"])
    member = user(**{field: f"service_{value}"})
    hit = inspect_user(member, settings, ["USDT"] if global_word else [])
    assert hit and hit["kind"] == "sensitive_word"


def test_emoji_and_decorative_symbols_can_be_blocked():
    assert inspect_user(user("nice😀"), policy(username_block_emoji=True))["kind"] == "emoji"
    assert inspect_user(user("꧁nice꧂"), policy(username_block_abnormal_chars=True))["kind"] == "abnormal_chars"


def test_normal_username_is_allowed():
    assert inspect_user(user("normal_user"), policy(username_block_emoji=True, username_block_abnormal_chars=True)) is None


async def test_disabled_review_skips_global_and_ai_checks(monkeypatch):
    await store.save_username_config(UsernameReviewConfig(sensitive_words=["scam"]))
    check = AsyncMock()
    monkeypatch.setattr(username_review.ai, "check_username", check)
    assert await username_review.inspect_with_ai(
        user("scam"), policy(username_review_enabled=False, username_ai_check=True),
    ) is None
    check.assert_not_awaited()


async def enable_ai_review(group_id):
    await store.save_policy(group_id, {
        "username_review_enabled": True, "username_ai_check": True,
        "welcome_enabled": True,
    })
    await store.save_ai_config(AIConfig(base_url="http://127.0.0.1:9/v1", text_model="test"))


async def test_ai_receives_both_labeled_name_fields(guard_group, monkeypatch):
    await enable_ai_review(guard_group)
    check = AsyncMock(return_value=(UsernameVerdict(safe=False, confidence=0.99, reason="显示名广告"), {}))
    monkeypatch.setattr(username_review.ai, "check_username", check)
    hit = await username_review.inspect_with_ai(
        user("ordinary_user", "可疑引流显示名"), await store.policy(guard_group),
    )
    assert hit and hit["kind"] == "ai"
    assert check.await_args.args[1] == "用户名：ordinary_user\n显示名：可疑引流显示名"


@pytest.mark.parametrize("is_request", [False, True])
@pytest.mark.parametrize("safe,confidence,rejected", [
    (False, 0.01, False), (False, 0.899, False), (False, 0.9, True),
    (False, 1.0, True), (True, 1.0, False),
])
async def test_ai_confidence_gates_both_join_paths(
    guard_group, guard_bot, guard_message, monkeypatch, is_request, safe, confidence, rejected
):
    await enable_ai_review(guard_group)
    await store.save_policy(guard_group, {"join_requests_enabled": True, "join_auto_approve": True})
    check = AsyncMock(return_value=(UsernameVerdict(safe=safe, confidence=confidence, reason="可疑名字"), {}))
    monkeypatch.setattr(username_review.ai, "check_username", check)
    message = guard_message()
    if is_request:
        update = Update.de_json({"update_id": 100, "chat_join_request": {
            "chat": message.chat.to_dict(), "from": message.from_user.to_dict(),
            "user_chat_id": 2, "date": int(message.date.timestamp()),
        }}, guard_bot)
        await verification.join_request(update, SimpleNamespace(bot=guard_bot))
        assert guard_bot.decline_chat_join_request.await_count == int(rejected)
        assert guard_bot.approve_chat_join_request.await_count == int(not rejected)
    else:
        await runtime.member_joined(guard_bot, message.chat, message.from_user, message.date)
        assert guard_bot.ban_chat_member.await_count == int(rejected)
        if not rejected:
            guard_bot.send_message.assert_awaited_once()
    check.assert_awaited_once()


async def test_slow_ai_releases_group_lock_and_deduplicates_joins(
    guard_group, guard_bot, guard_message, monkeypatch
):
    await enable_ai_review(guard_group)
    entered, release = asyncio.Event(), asyncio.Event()

    async def check_name(config, value):
        if "Member" in value:
            entered.set()
            await release.wait()
        return UsernameVerdict(safe=True, confidence=1, reason="正常"), {}

    check = AsyncMock(side_effect=check_name)
    monkeypatch.setattr(username_review.ai, "check_username", check)
    message = guard_message()
    task = asyncio.create_task(runtime.member_joined(
        guard_bot, message.chat, message.from_user, message.date,
        event_id=100, event_source="membership",
    ))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with asyncio.timeout(2):
            async with store.lock(guard_group):
                pass
            # The service-message duplicate must not launch another request.
            await runtime.member_joined(
                guard_bot, message.chat, message.from_user, message.date,
                event_id=101, event_source="service",
            )
            assert check.await_count == 1
            other = guard_message(**{"from": {"id": 3, "first_name": "Other", "is_bot": False}})
            await runtime.member_joined(guard_bot, other.chat, other.from_user, other.date)
        guard_bot.send_message.assert_awaited_once()
    finally:
        release.set()
        await asyncio.wait_for(task, 2)
    assert check.await_count == 2
    assert guard_bot.send_message.await_count == 2


@pytest.mark.parametrize("rejoin", [False, True])
async def test_old_ai_result_cannot_remove_departed_or_rejoined_member(
    guard_group, guard_bot, guard_message, monkeypatch, rejoin
):
    await enable_ai_review(guard_group)
    entered, release = asyncio.Event(), asyncio.Event()

    async def check_name(config, value):
        if not entered.is_set():
            entered.set()
            await release.wait()
            return UsernameVerdict(safe=False, confidence=1, reason="旧名字广告"), {}
        return UsernameVerdict(safe=True, confidence=1, reason="正常"), {}

    monkeypatch.setattr(username_review.ai, "check_username", AsyncMock(side_effect=check_name))
    message = guard_message()
    task = asyncio.create_task(runtime.member_joined(
        guard_bot, message.chat, message.from_user, message.date,
    ))
    generation = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with asyncio.timeout(2):
            await runtime.member_left(guard_group, 2, message.date)
            if rejoin:
                # Telegram timestamps have second precision: use the same second.
                await runtime.member_joined(guard_bot, message.chat, message.from_user, message.date)
                generation = (await store.record(guard_group, "join_seen", "2"))["data"]["generation"]
    finally:
        release.set()
        await asyncio.wait_for(task, 2)
    guard_bot.ban_chat_member.assert_not_awaited()
    assert guard_bot.send_message.await_count == int(rejoin)
    seen = await store.record(guard_group, "join_seen", "2")
    if rejoin:
        assert seen["data"]["generation"] == generation
    else:
        assert seen is None


async def test_cancelled_ai_join_remains_retryable(guard_group, guard_bot, guard_message, monkeypatch):
    await enable_ai_review(guard_group)
    entered = asyncio.Event()

    async def check_name(config, value):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(username_review.ai, "check_username", AsyncMock(side_effect=check_name))
    message = guard_message()
    task = asyncio.create_task(runtime.member_joined(
        guard_bot, message.chat, message.from_user, message.date,
    ))
    try:
        await asyncio.wait_for(entered.wait(), 2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await store.record(guard_group, "join_seen", "2") is None
    monkeypatch.setattr(username_review.ai, "check_username", AsyncMock(
        return_value=(UsernameVerdict(safe=True, confidence=1, reason="正常"), {}),
    ))
    await runtime.member_joined(guard_bot, message.chat, message.from_user, message.date)
    guard_bot.send_message.assert_awaited_once()


@pytest.mark.parametrize("leave_offset", [0, -1])
async def test_delayed_departure_cannot_invalidate_current_ai_review(
    guard_group, guard_bot, guard_message, monkeypatch, leave_offset
):
    await enable_ai_review(guard_group)
    entered, release = asyncio.Event(), asyncio.Event()

    async def check_name(config, value):
        entered.set()
        await release.wait()
        return UsernameVerdict(safe=False, confidence=1, reason="广告名字"), {}

    monkeypatch.setattr(username_review.ai, "check_username", AsyncMock(side_effect=check_name))
    message = guard_message()
    task = asyncio.create_task(runtime.member_joined(
        guard_bot, message.chat, message.from_user, message.date, event_id=200,
    ))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(runtime.member_left(
            guard_group, 2, message.date + timedelta(seconds=leave_offset), event_id=199,
        ), 2)
    finally:
        release.set()
        await asyncio.wait_for(task, 2)
    guard_bot.ban_chat_member.assert_awaited_once()


async def test_abandoned_ai_reservation_after_restart_is_retryable(guard_group, guard_bot, guard_message):
    message = guard_message()
    await store.put_record(guard_group, "join_seen", "2", {
        "timestamp": message.date.timestamp(), "generation": "stopped-process", "state": "checking",
    })
    await store.save_policy(guard_group, {"welcome_enabled": True})
    await runtime.member_joined(guard_bot, message.chat, message.from_user, message.date)
    guard_bot.send_message.assert_awaited_once()
    assert (await store.record(guard_group, "join_seen", "2"))["data"]["state"] == "done"


@pytest.mark.parametrize("is_request", [False, True])
async def test_global_username_hit_blocks_both_join_paths(guard_group, guard_bot, guard_message, is_request):
    await store.save_username_config(UsernameReviewConfig(sensitive_words=["scam"]))
    await store.save_policy(guard_group, {
        "username_review_enabled": True, "join_requests_enabled": True, "join_auto_approve": True,
    })
    identity = {"id": 2, "is_bot": False, "first_name": "User", "username": "SCAM_user"}
    context = SimpleNamespace(bot=guard_bot)
    if is_request:
        message = guard_message()
        update = Update.de_json({"update_id": 100, "chat_join_request": {
            "chat": {"id": guard_group, "type": "supergroup", "title": "Test"},
            "from": identity, "user_chat_id": 2, "date": int(message.date.timestamp()),
        }}, guard_bot)
        await verification.join_request(update, context)
        guard_bot.decline_chat_join_request.assert_awaited_once_with(guard_group, 2)
        guard_bot.approve_chat_join_request.assert_not_awaited()
        guard_bot.send_message.assert_not_awaited()
    else:
        joined = guard_message(text=None, new_chat_members=[identity])
        await runtime.preprocess(Update(100, message=joined), context)
        guard_bot.ban_chat_member.assert_awaited_once()
        guard_bot.send_message.assert_awaited_once_with(guard_group, REMOVAL_NOTICE, parse_mode=None)
        assert len(await deletion_jobs(guard_group)) == 1


async def deletion_jobs(group_id):
    async with engine.new_session() as session:
        return [store.dump(row) for row in await session.scalars(
            select(GuardTask).where(GuardTask.group_id == group_id, GuardTask.kind == "delete")
        )]


@pytest.mark.parametrize("membership_first", [False, True])
@pytest.mark.parametrize("clean_all", [False, True])
async def test_username_removal_cleans_both_service_messages_once_and_hides_identity(
    guard_group, guard_bot, guard_message, membership_first, clean_all
):
    await store.save_policy(guard_group, {
        "username_review_enabled": True, "username_sensitive_words": ["scam"],
        "goodbye_enabled": True, "clean_service_messages": clean_all,
    })
    identity = {"id": 2, "is_bot": False, "first_name": "Scam Display", "username": "scam_private"}
    joined = guard_message(text=None, message_id=31, new_chat_members=[identity])
    user = joined.new_chat_members[0]
    context = SimpleNamespace(bot=guard_bot)
    if membership_first:
        await runtime.member_joined(guard_bot, joined.chat, user, joined.date, event_id=100, event_source="membership")
    await runtime.preprocess(Update(101, message=joined), context)
    left = guard_message(
        text=None, message_id=32, date=int(joined.date.timestamp()) + 1,
        left_chat_member=identity,
        **{"from": {"id": guard_bot.id, "first_name": "Bot", "is_bot": True}},
    )
    await runtime.preprocess(Update(102, message=left), context)
    # Duplicate and delayed join notifications must neither kick nor notify again.
    await runtime.preprocess(Update(101, message=joined), context)
    await runtime.preprocess(Update(102, message=left), context)
    guard_bot.ban_chat_member.assert_awaited_once()
    guard_bot.send_message.assert_awaited_once_with(guard_group, REMOVAL_NOTICE, parse_mode=None)
    jobs = await deletion_jobs(guard_group)
    assert sorted(job["data"]["message_id"] for job in jobs) == [31, 32]
    for job in jobs:
        await worker.Worker(guard_bot).dispatch(job)
    assert sorted(call.args[1] for call in guard_bot.delete_message.await_args_list) == [31, 32]


async def test_unrelated_leave_does_not_get_deleted(guard_group, guard_bot, guard_message):
    await store.save_policy(guard_group, {
        "username_review_enabled": True, "username_sensitive_words": ["scam"], "goodbye_enabled": True,
    })
    identity = {"id": 2, "is_bot": False, "first_name": "scam"}
    joined = guard_message(text=None, new_chat_members=[identity])
    context = SimpleNamespace(bot=guard_bot)
    await runtime.preprocess(Update(100, message=joined), context)
    other = guard_message(text=None, message_id=40, left_chat_member={"id": 3, "is_bot": False, "first_name": "Other"})
    await runtime.preprocess(Update(101, message=other), context)
    assert [job["data"]["message_id"] for job in await deletion_jobs(guard_group)] == [10]
    assert "Other" in guard_bot.send_message.await_args.args[1]

    voluntary = guard_message(text=None, message_id=41, left_chat_member=identity)
    await runtime.preprocess(Update(102, message=voluntary), context)
    assert [job["data"]["message_id"] for job in await deletion_jobs(guard_group)] == [10]
    assert "scam" in guard_bot.send_message.await_args.args[1]


async def test_failed_removal_does_not_announce_success_or_delete_messages(guard_group, guard_bot, guard_message):
    await store.save_policy(guard_group, {"username_review_enabled": True, "username_sensitive_words": ["scam"]})
    guard_bot.ban_chat_member.side_effect = BadRequest("cannot remove")
    joined = guard_message(text=None, new_chat_members=[{"id": 2, "is_bot": False, "first_name": "scam"}])
    await runtime.preprocess(Update(100, message=joined), SimpleNamespace(bot=guard_bot))
    guard_bot.send_message.assert_not_awaited()
    assert await deletion_jobs(guard_group) == []


async def test_rejoin_has_fresh_removal_and_notice(guard_group, guard_bot, guard_message):
    await store.save_policy(guard_group, {"username_review_enabled": True, "username_sensitive_words": ["scam"]})
    identity = {"id": 2, "is_bot": False, "first_name": "scam"}
    joined = guard_message(text=None, new_chat_members=[identity])
    context = SimpleNamespace(bot=guard_bot)
    await runtime.preprocess(Update(100, message=joined), context)
    await runtime.member_left(guard_group, 2, joined.date + timedelta(seconds=1))
    again = guard_message(text=None, message_id=50, date=int(joined.date.timestamp()) + 5, new_chat_members=[identity])
    await runtime.preprocess(Update(102, message=again), context)
    assert guard_bot.ban_chat_member.await_count == 2
    assert guard_bot.send_message.await_count == 2
    assert sorted(job["data"]["message_id"] for job in await deletion_jobs(guard_group)) == [10, 50]


async def test_confirmed_ban_still_notifies_when_unban_fails(guard_group, guard_bot, guard_message):
    await store.save_policy(guard_group, {"username_review_enabled": True, "username_sensitive_words": ["scam"]})
    guard_bot.unban_chat_member.side_effect = BadRequest("cannot unban")
    joined = guard_message(text=None, new_chat_members=[{"id": 2, "is_bot": False, "first_name": "scam"}])
    await runtime.preprocess(Update(100, message=joined), SimpleNamespace(bot=guard_bot))
    guard_bot.send_message.assert_awaited_once_with(guard_group, REMOVAL_NOTICE, parse_mode=None)
    assert len(await deletion_jobs(guard_group)) == 1


async def test_deletion_failure_does_not_duplicate_notice(guard_group, guard_bot, guard_message):
    await store.save_policy(guard_group, {"username_review_enabled": True, "username_sensitive_words": ["scam"]})
    guard_bot.rights["can_delete_messages"] = False
    joined = guard_message(text=None, new_chat_members=[{"id": 2, "is_bot": False, "first_name": "scam"}])
    context = SimpleNamespace(bot=guard_bot)
    await runtime.preprocess(Update(100, message=joined), context)
    for job in await deletion_jobs(guard_group):
        await worker.Worker(guard_bot).dispatch(job)
        async with engine.new_session() as session:
            assert (await session.get(GuardTask, job["id"])).state == "failed"
    await runtime.preprocess(Update(100, message=joined), context)
    guard_bot.send_message.assert_awaited_once_with(guard_group, REMOVAL_NOTICE, parse_mode=None)
    guard_bot.delete_message.assert_not_awaited()


async def test_batch_join_only_queues_one_deletion(guard_group, guard_bot, guard_message):
    await store.save_policy(guard_group, {"username_review_enabled": True, "username_sensitive_words": ["scam"]})
    joined = guard_message(text=None, new_chat_members=[
        {"id": 2, "is_bot": False, "first_name": "scam one"},
        {"id": 3, "is_bot": False, "first_name": "scam two"},
    ])
    await runtime.preprocess(Update(100, message=joined), SimpleNamespace(bot=guard_bot))
    assert len(await deletion_jobs(guard_group)) == 1
    assert guard_bot.send_message.await_count == 2


async def test_join_message_arriving_after_kick_message_is_also_cleaned(guard_group, guard_bot, guard_message):
    await store.save_policy(guard_group, {"username_review_enabled": True, "username_sensitive_words": ["scam"], "goodbye_enabled": True})
    identity = {"id": 2, "is_bot": False, "first_name": "scam"}
    joined = guard_message(text=None, new_chat_members=[identity])
    await runtime.member_joined(guard_bot, joined.chat, joined.new_chat_members[0], joined.date)
    context = SimpleNamespace(bot=guard_bot)
    left = guard_message(text=None, message_id=11, date=int(joined.date.timestamp()) + 1, left_chat_member=identity,
                         **{"from": {"id": guard_bot.id, "first_name": "Bot", "is_bot": True}})
    await runtime.preprocess(Update(101, message=left), context)
    await runtime.preprocess(Update(100, message=joined), context)
    assert sorted(job["data"]["message_id"] for job in await deletion_jobs(guard_group)) == [10, 11]
    guard_bot.send_message.assert_awaited_once_with(guard_group, REMOVAL_NOTICE, parse_mode=None)
    guard_bot.ban_chat_member.assert_awaited_once()
