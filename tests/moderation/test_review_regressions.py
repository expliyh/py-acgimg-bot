"""Regression cases for automated review findings on PR #124."""

import asyncio
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update
from telegram import ChatMemberRestricted, Update
from telegram.error import BadRequest

from handlers.command_handlers import moderation_handler as commands
from models import GroupGuardPendingVerification as Pending
from models import GroupGuardSettings, GuardEvent, GuardRecord, GuardTask
from registries import engine
from services import group_guard
from services.moderation import (
    actions,
    ai,
    reviews,
    rules,
    runtime,
    store,
    verification,
    worker,
)
from services.moderation.schemas import (
    ActionRequest,
    AIConfig,
    AIVerdict,
    Content,
    Policy,
    Rule,
    validate_record_name,
)


def member_update(message, bot, *, actor=2, old=None, new=None):
    user = message.from_user.to_dict()
    return Update.de_json(
        {
            "update_id": 100,
            "chat_member": {
                "chat": message.chat.to_dict(),
                "from": {"id": actor, "first_name": "Actor", "is_bot": actor == bot.id},
                "date": int(message.date.timestamp()),
                "old_chat_member": old or {"status": "left", "user": user},
                "new_chat_member": new or {"status": "member", "user": user},
            },
        },
        bot,
    )


@pytest.mark.parametrize("actor", [2, 3], ids=["joining-member", "inviter"])
@pytest.mark.parametrize("service_first", [False, True])
async def test_join_updates_preserve_new_verification(
    guard_group, guard_bot, guard_message, actor, service_first
):
    await store.save_policy(guard_group, {"verification_enabled": True})
    message = guard_message()
    service_update = Update(
        99,
        message=guard_message(
            text=None, new_chat_members=[message.from_user.to_dict()]
        ),
    )
    context = SimpleNamespace(bot=guard_bot)
    if service_first:
        await runtime.preprocess(service_update, context)
    joined = member_update(message, guard_bot, actor=actor)
    await runtime.membership(joined, context)
    await runtime.membership(joined, context)
    if not service_first:
        await runtime.preprocess(service_update, context)
    async with engine.new_session() as session:
        pending = await session.get(Pending, (guard_group, 2))
        assert pending.state == "pending"
        token = pending.token
        assert await session.scalar(
            select(GuardEvent).where(GuardEvent.action == "membership")
        )
    guard_bot.restrict_chat_member.assert_awaited_once()
    assert await verification.finish(guard_bot, guard_group, 2, token) == "验证通过"


async def test_later_external_permission_change_still_stops_verification(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"verification_enabled": True})
    message = guard_message()
    context = SimpleNamespace(bot=guard_bot)
    await runtime.membership(member_update(message, guard_bot), context)
    restricted = {
        "status": "restricted",
        "user": message.from_user.to_dict(),
        "is_member": True,
        "until_date": 0,
        **{
            field: False
            for field in ChatMemberRestricted.__slots__
            if field.startswith("can_")
        },
    }
    await runtime.membership(
        member_update(
            message,
            guard_bot,
            actor=1,
            old=restricted,
            new=restricted | {"can_send_messages": True},
        ),
        context,
    )
    async with engine.new_session() as session:
        pending = await session.get(Pending, (guard_group, 2))
        assert pending.state == "external"
        token = pending.token
    assert (
        await verification.finish(guard_bot, guard_group, 2, token)
        == "验证已失效或已处理"
    )
    guard_bot.restrict_chat_member.assert_awaited_once()


async def test_policy_save_serializes_with_legacy_setting_writes(
    guard_group, monkeypatch
):
    policy_read = asyncio.Event()
    release_save = asyncio.Event()
    original_policy = store.policy

    async def delayed_policy(group_id):
        value = await original_policy(group_id)
        policy_read.set()
        await release_save.wait()
        return value

    monkeypatch.setattr(store, "policy", delayed_policy)
    policy_save = asyncio.create_task(store.save_policy(guard_group, {"ai_spam": True}))
    await policy_read.wait()
    legacy_save = asyncio.create_task(
        group_guard.set_verification_enabled(guard_group, True)
    )
    await asyncio.sleep(0)
    assert not legacy_save.done()
    release_save.set()
    await asyncio.gather(policy_save, legacy_save)

    saved = await original_policy(guard_group)
    assert saved.ai_spam is True
    assert saved.verification_enabled is True


async def test_telegram_content_removal_cancels_announcement_task(
    guard_group, guard_bot, guard_message
):
    await worker.save_content(
        guard_group,
        Content(
            kind="announcement",
            name="future",
            text="hello",
            due_at=store.now().replace(tzinfo=timezone.utc) + timedelta(days=30),
        ),
    )
    update = Update(201, message=guard_message(text="/guard content remove"))
    assert await commands.guard_extra(
        update,
        SimpleNamespace(
            bot=guard_bot,
            args=["content", "remove", "announcement", "future"],
        ),
    )

    assert await store.record(guard_group, "announcement", "future") is None
    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(GuardTask.kind == "announcement")
        )
        assert task.state == "cancelled"


def test_content_names_are_trimmed_and_must_not_be_blank():
    assert Content(kind="reply", name="  trigger  ", text="hello").name == "trigger"
    with pytest.raises(ValueError, match="内容名称不能为空"):
        Content(kind="reply", name=" \t ", text="hello")
    with pytest.raises(ValueError, match="不能包含斜杠"):
        Content(kind="reply", name="path/segment", text="hello")


async def test_distinct_attachment_only_polls_do_not_count_as_repeats(
    guard_group, guard_message
):
    settings = Policy(flood_enabled=True, flood_limit=100, repeat_limit=3)

    def poll(poll_id, message_id):
        return guard_message(
            message_id=message_id,
            text=None,
            poll={
                "id": poll_id,
                "question": "Choose",
                "options": [
                    {"text": "A", "voter_count": 0, "persistent_id": "a"},
                    {"text": "B", "voter_count": 0, "persistent_id": "b"},
                ],
                "total_voter_count": 0,
                "is_closed": False,
                "is_anonymous": True,
                "type": "regular",
                "allows_multiple_answers": False,
                "allows_revoting": False,
                "members_only": False,
            },
        )

    messages = [poll(f"poll-{index}", 20 + index) for index in range(3)]
    assert len({rules.fingerprint(value) for value in messages}) == 3
    for value in messages:
        assert await rules.evaluate(value, settings) is None


async def test_media_album_counts_as_one_flood_message(guard_group, guard_message):
    settings = Policy(flood_enabled=True, flood_limit=6, repeat_limit=50)
    for index in range(7):
        item = guard_message(
            message_id=30 + index,
            text=None,
            media_group_id="album-1",
            photo=[
                {
                    "file_id": f"photo-{index}",
                    "file_unique_id": f"unique-{index}",
                    "width": 100,
                    "height": 100,
                }
            ],
        )
        assert await rules.evaluate(item, settings) is None


async def test_combined_rule_reason_fits_action_request(guard_group, guard_message):
    for index in range(11):
        name = f"{index:02d}-" + "x" * 97
        await store.put_record(
            guard_group,
            "rule",
            name,
            {"kind": "keyword", "pattern": "spam", "action": "delete_warn"},
        )
    result = await rules.evaluate(
        guard_message(text="spam"), Policy(rules_enabled=True)
    )

    assert len(result["reason"]) == 1000
    ActionRequest(
        action="delete",
        message_id=10,
        request_id="bounded-rule-reason",
        reason=result["reason"],
    )


async def test_new_message_version_retries_definitive_delete_failure(
    guard_group, guard_bot
):
    await store.put_record(
        guard_group, "message", "10", {"version": "version-one", "blocked": False}
    )
    guard_bot.delete_message.side_effect = BadRequest("missing permission")
    first = await actions.punish(
        guard_bot,
        guard_group,
        2,
        10,
        "message:10",
        "spam",
        warn=False,
        expected={"version": "version-one"},
    )
    assert first[0]["status"] == "failed"

    await store.put_record(
        guard_group, "message", "10", {"version": "version-two", "blocked": False}
    )
    guard_bot.delete_message.side_effect = None
    second = await actions.punish(
        guard_bot,
        group_id=guard_group,
        user_id=2,
        message_id=10,
        incident="message:10",
        reason="spam",
        warn=False,
        expected={"version": "version-two"},
    )
    assert second[0]["status"] == "success"
    assert guard_bot.delete_message.await_count == 2


async def test_unicode_format_only_keywords_are_rejected(guard_group):
    with pytest.raises(ValueError, match="不能为空"):
        Rule(kind="keyword", pattern="\u200b\u200d")
    with pytest.raises(ValueError, match="不能为空"):
        await group_guard.add_keyword_rule(guard_group, "\u200b\u200d")
    assert not rules.matches(
        {"kind": "keyword", "pattern": "\u200b"},
        SimpleNamespace(text="ordinary", caption=None),
        [],
    )


async def test_legacy_empty_normalized_reply_does_not_match_every_message(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"replies_enabled": True})
    await store.put_record(
        guard_group,
        "reply",
        "\u200b",
        {"kind": "reply", "name": "\u200b", "text": "unexpected"},
    )

    await runtime.operations(
        Update(1, message=guard_message(text="ordinary")),
        SimpleNamespace(bot=guard_bot),
    )

    guard_bot.send_message.assert_not_awaited()


def test_rule_names_are_safe_api_path_segments():
    assert validate_record_name("  spam  ", "规则名称") == "spam"
    with pytest.raises(ValueError, match="不能为空"):
        validate_record_name(" \t ", "规则名称")
    with pytest.raises(ValueError, match="路径片段"):
        validate_record_name("folder/rule", "规则名称")
    with pytest.raises(ValueError, match="路径片段"):
        validate_record_name("..", "规则名称")
    with pytest.raises(ValueError, match="过长"):
        validate_record_name("x" * 101, "规则名称")


async def test_migrate_from_service_message_moves_guard_state(
    guard_group, guard_bot, guard_message
):
    new_id = guard_group - 1
    await store.save_policy(guard_group, {"flood_enabled": True})
    update = Update(
        1,
        message=guard_message(
            chat={"id": new_id, "type": "supergroup", "title": "Upgraded"},
            migrate_from_chat_id=guard_group,
        ),
    )

    await runtime.preprocess(update, SimpleNamespace(bot=guard_bot))

    assert (await store.policy(new_id)).flood_enabled
    assert not (await store.policy(guard_group)).flood_enabled


PHOTO = [
    {"file_id": "photo", "file_unique_id": "unique-photo", "width": 100, "height": 100}
]
IMAGE = {"file_id": "image", "file_unique_id": "unique-image", "mime_type": "image/png"}
PDF = {"file_id": "pdf", "file_unique_id": "unique-pdf", "mime_type": "application/pdf"}
VIDEO = {
    "file_id": "video",
    "file_unique_id": "unique-video",
    "width": 100,
    "height": 100,
    "duration": 1,
}


@pytest.mark.parametrize(
    "policy,content,queued",
    [
        ({"ai_images": True}, {"text": "plain text"}, False),
        (
            {"ai_images": True},
            {"text": None, "document": PDF, "caption": "caption"},
            False,
        ),
        (
            {"ai_images": True},
            {"text": None, "video": VIDEO, "caption": "caption"},
            False,
        ),
        ({"ai_images": True}, {"text": None, "photo": PHOTO}, True),
        ({"ai_images": True}, {"text": None, "document": IMAGE}, True),
        ({"ai_spam": True}, {"text": "plain text"}, True),
        (
            {"ai_abuse": True},
            {"text": None, "photo": PHOTO, "caption": "caption"},
            True,
        ),
        ({"ai_spam": True}, {"text": None, "photo": PHOTO}, False),
        ({"ai_abuse": True}, {"text": None, "video": VIDEO}, False),
    ],
)
async def test_only_relevant_content_enters_ai_queue(
    guard_group, guard_bot, guard_message, policy, content, queued
):
    await store.save_policy(guard_group, policy)
    await store.save_ai_config(
        AIConfig(base_url="http://127.0.0.1:9/v1", vision_model="test-vision")
    )
    message = guard_message(**content)
    await runtime.preprocess(Update(1, message=message), SimpleNamespace(bot=guard_bot))
    async with engine.new_session() as session:
        tasks = (
            await session.scalars(select(GuardTask).where(GuardTask.kind == "ai"))
        ).all()
        assert len(tasks) == int(queued)
        if queued:
            assert tasks[0].data["version"] == rules.version(message)


@pytest.mark.parametrize("text_model", ["", "test-text"])
async def test_preexisting_irrelevant_ai_jobs_do_not_consume_budget(
    guard_group, guard_bot, guard_ai_job, monkeypatch, text_model
):
    job = await guard_ai_job(
        policy={"ai_spam": False, "ai_images": True, "ai_daily_limit": 1}
    )
    await store.save_ai_config(
        AIConfig(
            base_url="http://127.0.0.1:9/v1",
            text_model=text_model,
            vision_model="test-vision",
        )
    )
    classifier = AsyncMock(
        return_value=(AIVerdict(category="safe", confidence=1, reason="safe"), {})
    )
    monkeypatch.setattr(ai, "classify", classifier)
    assert await ai.process(guard_bot, job) == "skipped"
    classifier.assert_not_awaited()
    async with engine.new_session() as session:
        assert (
            await session.scalar(select(GuardEvent).where(GuardEvent.action == "ai"))
            is None
        )


async def test_cleanup_expires_temporary_records_without_audit_events(
    guard_group, guard_bot
):
    old_ids = []
    for kind in ("message", "join_seen", "note", "review", "exempt"):
        row = await store.put_record(guard_group, kind, "old", {})
        old_ids.append(row["id"])
    await store.put_record(guard_group, "message", "recent", {})
    other = await store.put_record(guard_group + 1, "message", "old", {})
    old_ids.append(other["id"])
    async with engine.new_session() as session:
        assert await session.scalar(select(GuardEvent)) is None
        await session.execute(
            update(GuardRecord)
            .where(GuardRecord.id.in_(old_ids))
            .values(
                created_at=store.now() - timedelta(days=3),
            )
        )
        await session.commit()
    await worker.Worker(guard_bot).cleanup()
    assert await store.record(guard_group, "message", "old") is None
    assert await store.record(guard_group, "join_seen", "old") is None
    assert await store.record(guard_group + 1, "message", "old") is None
    assert await store.record(guard_group, "message", "recent")
    for kind in ("note", "review", "exempt"):
        assert await store.record(guard_group, kind, "old")


async def test_cleanup_discovers_task_only_groups(guard_group, guard_bot):
    await store.save_policy(guard_group, {"log_days": 7})
    ended = await store.task(guard_group, "delete", store.now(), {})
    uncertain = await store.task(guard_group, "announcement", store.now(), {})
    await worker.set_state(ended, "done")
    await worker.set_state(uncertain, "uncertain")
    async with engine.new_session() as session:
        assert await session.scalar(select(GuardEvent)) is None
        await session.execute(
            update(GuardTask).values(created_at=store.now() - timedelta(days=8))
        )
        await session.commit()
    await worker.Worker(guard_bot).cleanup()
    async with engine.new_session() as session:
        assert await session.get(GuardTask, ended) is None
        assert (await session.get(GuardTask, uncertain)).state == "uncertain"


@pytest.mark.parametrize("tracked", [False, True])
@pytest.mark.parametrize("edited", [False, True])
async def test_report_version_controls_later_punishment(
    guard_group, guard_bot, guard_message, tracked, edited
):
    reported = guard_message(text="reported content")
    context = SimpleNamespace(bot=guard_bot, args=[])
    if tracked:
        await runtime.preprocess(Update(1, message=reported), context)
    report = guard_message(
        message_id=11, text="/report", reply_to_message=reported.to_dict()
    )
    await commands.moderation_command(Update(2, message=report), context)
    key = f"report:10:{rules.version(reported)}"
    row = await store.record(guard_group, "review", key)
    assert row["data"].get("version") == rules.version(reported)
    if edited:
        changed = guard_message(
            text="corrected content", edit_date=int(reported.date.timestamp()) + 1
        )
        await runtime.preprocess(Update(3, edited_message=changed), context)
    result = await reviews.decide(
        guard_bot, guard_group, row["id"], "punish", "reported", actor_id=1
    )
    if edited:
        assert result["data"]["state"] == "failed"
        guard_bot.delete_message.assert_not_awaited()
        assert await store.warnings(guard_group, 2) == []
    else:
        assert result["data"]["state"] == "resolved"
        guard_bot.delete_message.assert_awaited_once_with(guard_group, 10)
        assert len(await store.warnings(guard_group, 2)) == 1


async def test_report_reply_never_overwrites_newer_observed_version(
    guard_group, guard_bot, guard_message
):
    original = guard_message(text="old text")
    latest = guard_message(
        text="edited text", edit_date=int(original.date.timestamp()) + 1
    )
    context = SimpleNamespace(bot=guard_bot, args=[])
    await runtime.preprocess(Update(1, edited_message=latest), context)
    report = guard_message(
        message_id=11, text="/report", reply_to_message=original.to_dict()
    )
    await commands.moderation_command(Update(2, message=report), context)
    assert (await store.record(guard_group, "message", "10"))["data"][
        "version"
    ] == rules.version(latest)
    row = await store.record(
        guard_group, "review", f"report:10:{rules.version(original)}"
    )
    result = await reviews.decide(
        guard_bot, guard_group, row["id"], "punish", "old report", actor_id=1
    )
    assert result["data"]["state"] == "failed"
    guard_bot.delete_message.assert_not_awaited()


async def test_exempt_member_edit_still_invalidates_older_review_version(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"rules_enabled": True})
    original = guard_message(text="old text")
    context = SimpleNamespace(bot=guard_bot)
    await runtime.preprocess(Update(1, message=original), context)
    await store.put_record(guard_group, "exempt", "2", {})
    edited = guard_message(
        text="new text", edit_date=int(original.date.timestamp()) + 1
    )

    await runtime.preprocess(Update(2, edited_message=edited), context)

    assert (await store.record(guard_group, "message", "10"))["data"][
        "version"
    ] == rules.version(edited)


async def test_edited_message_can_be_reported_again_after_stale_review(
    guard_group, guard_bot, guard_message
):
    original = guard_message(text="old text")
    context = SimpleNamespace(bot=guard_bot, args=[])
    first_report = guard_message(
        message_id=11, text="/report", reply_to_message=original.to_dict()
    )
    await commands.moderation_command(Update(1, message=first_report), context)
    first = await store.record(
        guard_group, "review", f"report:10:{rules.version(original)}"
    )

    edited = guard_message(
        text="new text", edit_date=int(original.date.timestamp()) + 1
    )
    await runtime.preprocess(Update(2, edited_message=edited), context)
    stale = await reviews.decide(
        guard_bot, guard_group, first["id"], "punish", "old report", actor_id=1
    )
    assert stale["data"]["state"] == "failed"

    second_report = guard_message(
        message_id=12, text="/report", reply_to_message=edited.to_dict()
    )
    await commands.moderation_command(Update(3, message=second_report), context)
    second = await store.record(
        guard_group, "review", f"report:10:{rules.version(edited)}"
    )
    assert second and second["id"] != first["id"]
    assert second["data"]["state"] == "pending"
    assert len(await store.records(guard_group, "review")) == 2


async def test_review_rechecks_version_after_entering_action_lock(
    guard_group, guard_bot, guard_message, monkeypatch
):
    message = guard_message(text="reported")
    version = rules.version(message)
    await store.put_record(
        guard_group, "message", "10", {"version": version, "blocked": False}
    )
    row = await reviews.create(
        guard_group,
        f"report:10:{version}",
        {
            "kind": "message",
            "user_id": 2,
            "message_id": 10,
            "version": version,
            "incident": "message:10",
        },
    )
    reached_action = asyncio.Event()
    release_action = asyncio.Event()
    original = actions.punish

    async def delayed(*args, **kwargs):
        reached_action.set()
        await release_action.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(reviews.actions, "punish", delayed)
    decision = asyncio.create_task(
        reviews.decide(guard_bot, guard_group, row["id"], "punish", "spam", actor_id=1)
    )
    await reached_action.wait()
    await store.put_record(
        guard_group, "message", "10", {"version": "edited", "blocked": False}
    )
    release_action.set()
    result = await decision

    assert result["data"]["state"] == "failed"
    guard_bot.delete_message.assert_not_awaited()
    assert await store.warnings(guard_group, 2) == []


async def test_policy_repairs_oversized_legacy_verification_message(
    guard_group,
):
    legacy_message = "旧" * 2001
    async with engine.new_session() as session:
        session.add(
            GroupGuardSettings(
                group_id=guard_group, verification_message=legacy_message
            )
        )
        await session.commit()

    assert (
        await group_guard.get_guard_settings(guard_group)
    ).verification_message == legacy_message
    policy = await store.policy(guard_group)
    assert policy.verification_message == legacy_message[:2000]

    async with engine.new_session() as session:
        row = await session.get(GroupGuardSettings, guard_group)
        assert row.verification_message == legacy_message[:2000]
    assert (
        await group_guard.get_guard_settings(guard_group)
    ).verification_message == legacy_message[:2000]


async def test_legacy_verification_setter_rejects_new_oversized_messages(
    guard_group,
):
    with pytest.raises(ValueError, match="2000"):
        await group_guard.set_verification_message(guard_group, "x" * 2001)
