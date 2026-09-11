"""Focused regression coverage for bot join approval and bot moderation."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from telegram import Chat, Update, User
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import ApplicationHandlerStop

from models import GuardTask
from registries import engine
from services.moderation import bot_approval, reviews, runtime, store, worker
from services.moderation import verification
from services.moderation.schemas import Rule


def bot_member(user, *, status="member", can_send_messages=True):
    return SimpleNamespace(
        user=user,
        status=status,
        is_member=True,
        can_send_messages=can_send_messages,
        can_restrict_members=True,
        can_delete_messages=True,
        can_invite_users=True,
    )


@pytest.fixture
def helper_bot(guard_bot):
    user = User(12345, "Helper", True, username="helper_bot")
    guard_bot.members[user.id] = bot_member(user)
    return user


async def test_join_creates_indefinite_bot_review_and_blocks_first_message(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["state"] == "pending"
    assert record["data"]["restricted"] is True
    rows = await store.records(guard_group, "review", enabled=True)
    assert rows[0]["data"]["kind"] == "bot_join"

    message = guard_message(
        **{"from": {"id": helper_bot.id, "first_name": "Helper", "username": "helper_bot", "is_bot": True}}
    )
    with pytest.raises(ApplicationHandlerStop):
        await runtime.preprocess(Update(1, message=message), SimpleNamespace(bot=guard_bot))
    guard_bot.delete_message.assert_awaited_once()


async def test_bot_review_approve_restores_permissions_and_enables_record(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    review = (await store.records(guard_group, "review", enabled=True))[0]
    result = await reviews.decide(
        guard_bot,
        guard_group,
        review["id"],
        "approve_bot",
        "已核查",
        actor_id=1,
    )
    assert result["data"]["state"] == "resolved"
    assert (await bot_approval.approval_status(guard_group, helper_bot.id))["data"][
        "state"
    ] == "approved"


async def test_bot_review_rejects_with_rejoinable_kick(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    review = (await store.records(guard_group, "review", enabled=True))[0]
    result = await reviews.decide(
        guard_bot,
        guard_group,
        review["id"],
        "reject_bot",
        "不批准",
        actor_id=1,
    )
    assert result["data"]["state"] == "resolved"
    guard_bot.ban_chat_member.assert_awaited_once()
    guard_bot.unban_chat_member.assert_awaited_once_with(
        guard_group, helper_bot.id, only_if_banned=True
    )
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["state"] == "rejected" and not record["enabled"]


async def test_definitive_bot_approval_failure_keeps_review_retryable(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    review = (await store.records(guard_group, "review", enabled=True))[0]
    guard_bot.restrict_chat_member.side_effect = BadRequest("permission revoked")

    result = await reviews.decide(
        guard_bot,
        guard_group,
        review["id"],
        "approve_bot",
        "retry after fixing permissions",
        actor_id=1,
    )

    assert result["data"]["state"] == "pending"
    approval = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert approval["data"]["state"] == "pending"
    assert approval["enabled"] is True


async def test_uncertain_restriction_is_not_replayed_on_duplicate_join(
    guard_group, guard_bot, helper_bot, guard_message
):
    guard_bot.restrict_chat_member.side_effect = TimedOut()
    chat = Chat(guard_group, "supergroup", title="Test group")
    when = guard_message().date
    await runtime.member_joined(guard_bot, chat, helper_bot, when)
    await runtime.member_joined(
        guard_bot, chat, helper_bot, when + timedelta(seconds=1)
    )
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["state"] == "uncertain"
    assert guard_bot.restrict_chat_member.await_count == 1


async def test_rate_limited_restriction_is_durable_and_retryable(
    guard_group, guard_bot, helper_bot, guard_message
):
    guard_bot.restrict_chat_member.side_effect = RetryAfter(3)
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["state"] == "pending"
    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group,
                GuardTask.kind == "bot_restrict",
            )
        )
        assert task is not None and task.data["generation"] == record["data"]["generation"]


async def test_restart_preserves_confirmed_restriction_rate_limit(
    guard_group, guard_bot, helper_bot, guard_message
):
    guard_bot.restrict_chat_member.side_effect = RetryAfter(30)
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group,
                GuardTask.kind == "bot_restrict",
            )
        )
        task.state = "running"
        task_id = task.id
        await session.commit()
    await worker.Worker(guard_bot).recover()
    async with engine.new_session() as session:
        recovered = await session.get(GuardTask, task_id)
        assert recovered.state == "pending"
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["state"] == "pending"


async def test_lookup_timeout_marks_bot_review_uncertain(
    guard_group, guard_bot, helper_bot, guard_message
):
    guard_bot.get_chat_member.side_effect = TimedOut()
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    review = (await store.records(guard_group, "review"))[0]
    assert record["data"]["state"] == "uncertain"
    assert review["data"]["state"] == "uncertain"


async def test_rate_limited_lookup_captures_snapshot_before_retry(
    guard_group, guard_bot, helper_bot, guard_message
):
    prior = SimpleNamespace(
        user=helper_bot,
        status="restricted",
        is_member=True,
        can_send_messages=True,
        can_send_photos=True,
        can_send_videos=False,
        until_date=None,
    )
    admin = bot_member(User(999, "Main", True), status="administrator")
    guard_bot.get_chat_member.side_effect = [RetryAfter(1), prior, admin]
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group,
                GuardTask.kind == "bot_restrict",
            )
        )
        job = store.dump(task)
    current = await bot_approval.approval_status(guard_group, helper_bot.id)
    retry_data = dict(current["data"])
    retry_data["retry_at"] = (store.now() - timedelta(seconds=1)).isoformat()
    await store.put_record(guard_group, "bot_approval", str(helper_bot.id), retry_data)
    await worker.Worker(guard_bot).dispatch(job)
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["original"]["permissions"]["can_send_photos"] is True
    assert record["data"]["original_captured"] is True


async def test_basic_group_keeps_bot_pending_without_restriction_call(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "group", title="Basic group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["state"] == "pending"
    guard_bot.restrict_chat_member.assert_not_awaited()


async def test_basic_group_first_message_stays_blocked_without_external_approval(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "group", title="Basic group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    message = guard_message(
        **{
            "chat": {"id": guard_group, "type": "group", "title": "Basic group"},
            "from": {
                "id": helper_bot.id,
                "first_name": "Helper",
                "is_bot": True,
            },
        }
    )
    with pytest.raises(ApplicationHandlerStop):
        await runtime.preprocess(Update(12, message=message), SimpleNamespace(bot=guard_bot))
    assert guard_bot.delete_message.await_count == 1


async def test_uncertain_release_is_not_replayed_after_restart(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})
    guard_bot.restrict_chat_member.side_effect = TimedOut()
    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group, GuardTask.kind == "bot_release"
            )
        )
        job = store.dump(task)
    await worker.Worker(guard_bot).dispatch(job)
    guard_bot.restrict_chat_member.reset_mock()
    guard_bot.restrict_chat_member.side_effect = None
    restarted = worker.Worker(guard_bot)
    await restarted.recover()
    await restarted.tick()
    guard_bot.restrict_chat_member.assert_not_awaited()
    async with engine.new_session() as session:
        task = await session.get(GuardTask, job["id"])
        assert task.state == "uncertain"


async def test_update_id_keeps_delayed_leave_from_erasing_new_bot_generation(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    when = guard_message().date
    await runtime.member_joined(
        guard_bot, chat, helper_bot, when, event_id=10, event_source="membership"
    )
    await runtime.member_left(guard_group, helper_bot.id, when, event_id=11)
    await runtime.member_joined(
        guard_bot, chat, helper_bot, when, event_id=20, event_source="membership"
    )
    current = await bot_approval.approval_status(guard_group, helper_bot.id)
    await runtime.member_left(guard_group, helper_bot.id, when, event_id=15)
    assert (
        await bot_approval.approval_status(guard_group, helper_bot.id)
    )["data"]["generation"] == current["data"]["generation"]


async def test_newer_join_update_creates_new_generation_even_in_same_second(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    when = guard_message().date
    await runtime.member_joined(
        guard_bot,
        chat,
        helper_bot,
        when,
        event_id=10,
        event_source="membership",
    )
    first = await bot_approval.approval_status(guard_group, helper_bot.id)

    # Telegram timestamps only have second precision.  A newer update ID is
    # still an authoritative new membership generation.
    await runtime.member_joined(
        guard_bot,
        chat,
        helper_bot,
        when,
        event_id=20,
        event_source="membership",
    )
    second = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert second["data"]["generation"] != first["data"]["generation"]
    assert guard_bot.restrict_chat_member.await_count == 2


async def test_service_and_chat_member_join_updates_are_idempotent(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    when = guard_message().date
    await runtime.member_joined(
        guard_bot, chat, helper_bot, when, event_id=30, event_source="service"
    )
    await runtime.member_joined(
        guard_bot, chat, helper_bot, when, event_id=31, event_source="membership"
    )
    assert guard_bot.restrict_chat_member.await_count == 1


async def test_worker_recovery_rebuilds_missing_release_task(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})
    async with engine.new_session() as session:
        await session.execute(
            __import__("sqlalchemy").delete(GuardTask).where(
                GuardTask.group_id == guard_group, GuardTask.kind == "bot_release"
            )
        )
        await session.commit()
    await worker.Worker(guard_bot).recover()
    rows = await store.records(guard_group, "bot_approval")
    assert rows
    async with engine.new_session() as session:
        tasks = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == guard_group,
                    GuardTask.kind == "bot_release",
                    GuardTask.state == "pending",
                )
            )
        ).all()
    assert len(tasks) == 1


async def test_recovery_surfaces_release_claimed_before_record_phase(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    review = (await store.records(guard_group, "review", enabled=True))[0]
    await reviews.decide(
        guard_bot, guard_group, review["id"], "approve_bot", "ok", actor_id=1
    )
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})
    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group, GuardTask.kind == "bot_release"
            )
        )
        task.state = "running"
        task_id = task.id
        await session.commit()

    await worker.Worker(guard_bot).recover()
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["state"] == "uncertain"
    review_row = (await store.records(guard_group, "review"))[0]
    assert review_row["data"]["state"] == "uncertain"
    async with engine.new_session() as session:
        assert (await session.get(GuardTask, task_id)).state == "uncertain"


async def test_disabling_approval_queues_release_and_worker_cleans_record(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})
    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group, GuardTask.kind == "bot_release"
            )
        )
        assert task is not None
        job = store.dump(task)
    await worker.Worker(guard_bot).dispatch(job)
    assert await bot_approval.approval_status(guard_group, helper_bot.id) is None


async def test_restricted_bot_stays_blocked_until_release_task_finishes(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})

    message = guard_message(
        **{"from": {"id": helper_bot.id, "first_name": "Helper", "is_bot": True}}
    )
    with pytest.raises(ApplicationHandlerStop):
        await runtime.preprocess(
            Update(45, message=message), SimpleNamespace(bot=guard_bot)
        )
    guard_bot.delete_message.assert_awaited_once()

    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group, GuardTask.kind == "bot_release"
            )
        )
        job = store.dump(task)
    await worker.Worker(guard_bot).dispatch(job)
    assert await bot_approval.approval_status(guard_group, helper_bot.id) is None


async def test_reenabling_before_release_does_not_reuse_old_approval(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    review = (await store.records(guard_group, "review", enabled=True))[0]
    await reviews.decide(guard_bot, guard_group, review["id"], "approve_bot", "ok", actor_id=1)
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})
    await store.save_policy(guard_group, {"bot_join_approval_enabled": True})
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["release_pending"] is True
    with pytest.raises(ApplicationHandlerStop):
        await runtime.preprocess(
            Update(
                44,
                message=guard_message(
                    **{"from": {"id": helper_bot.id, "first_name": "Helper", "is_bot": True}}
                ),
            ),
            SimpleNamespace(bot=guard_bot),
        )


async def test_old_release_task_cannot_remove_fresh_external_approval(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    review = (await store.records(guard_group, "review", enabled=True))[0]
    await reviews.decide(guard_bot, guard_group, review["id"], "approve_bot", "ok", actor_id=1)
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})
    await store.save_policy(guard_group, {"bot_join_approval_enabled": True})
    restored = bot_member(helper_bot, status="restricted", can_send_messages=True)
    assert await bot_approval.external_permission_change(guard_group, restored)
    async with engine.new_session() as session:
        release = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group, GuardTask.kind == "bot_release"
            )
        )
        job = store.dump(release)
    assert await bot_approval.release_task(guard_bot, job) == "stale"
    current = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert current["data"]["state"] == "approved"


async def test_bot_moderation_switch_controls_rules(
    guard_group, guard_bot, helper_bot, guard_message
):
    await store.save_policy(
        guard_group,
        {"bot_join_approval_enabled": False, "rules_enabled": True},
    )
    await store.put_record(
        guard_group,
        "rule",
        "spam",
        Rule(kind="keyword", pattern="spam").model_dump(),
    )
    message = guard_message(
        **{"from": {"id": helper_bot.id, "first_name": "Helper", "is_bot": True}},
        text="spam",
    )
    # The bot is not approved because join approval is disabled, but content
    # moderation is also disabled for bots by default.
    await runtime.preprocess(Update(2, message=message), SimpleNamespace(bot=guard_bot))
    guard_bot.delete_message.assert_not_awaited()
    await store.save_policy(guard_group, {"bot_moderation_enabled": True})
    with pytest.raises(ApplicationHandlerStop):
        await runtime.preprocess(
            Update(3, message=guard_message(
                message_id=11,
                **{"from": {"id": helper_bot.id, "first_name": "Helper", "is_bot": True}},
                text="spam",
            )),
            SimpleNamespace(bot=guard_bot),
        )
    assert guard_bot.delete_message.await_count >= 1


async def test_duplicate_join_is_idempotent_and_admin_bot_is_exempt(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    when = guard_message().date
    await runtime.member_joined(guard_bot, chat, helper_bot, when)
    await runtime.member_joined(guard_bot, chat, helper_bot, when)
    assert guard_bot.restrict_chat_member.await_count == 1
    assert len(await store.records(guard_group, "review", enabled=True)) == 1

    admin_user = User(12346, "AdminBot", True, username="admin_bot")
    guard_bot.members[admin_user.id] = bot_member(admin_user, status="administrator")
    await runtime.member_joined(guard_bot, chat, admin_user, when)
    admin_record = await bot_approval.approval_status(guard_group, admin_user.id)
    assert admin_record["data"]["state"] == "approved"
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})
    # The release worker has no Telegram restriction to undo for an admin bot.
    await worker.Worker(guard_bot).recover()
    guard_bot.restrict_chat_member.reset_mock()
    async with engine.new_session() as session:
        task = next(
            (
                row
                for row in (
                    await session.scalars(
                        select(GuardTask).where(
                            GuardTask.group_id == guard_group,
                            GuardTask.kind == "bot_release",
                        )
                    )
                ).all()
                if row.data.get("user_id") == admin_user.id
            ),
            None,
        )
        if task:
            await worker.Worker(guard_bot).dispatch(store.dump(task))
    guard_bot.restrict_chat_member.assert_not_awaited()


async def test_external_restriction_restore_approves_current_generation(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    restored = bot_member(helper_bot, status="restricted", can_send_messages=True)
    assert await bot_approval.external_permission_change(guard_group, restored)
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"]["state"] == "approved"
    review = (await store.records(guard_group, "review"))[0]
    assert review["data"]["state"] == "resolved"


async def test_external_approval_retires_uncertain_generation_task(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    task_id = store.uid()
    async with engine.new_session() as session:
        task = GuardTask(
            id=task_id,
            group_id=guard_group,
            kind="bot_restrict",
            state="uncertain",
            due_at=store.now(),
            data={
                "user_id": helper_bot.id,
                "generation": record["data"]["generation"],
            },
            created_at=store.now(),
        )
        session.add(task)
        await session.commit()

    restored = bot_member(helper_bot, status="restricted", can_send_messages=True)
    assert await bot_approval.external_permission_change(guard_group, restored)
    await worker.Worker(guard_bot).recover()
    current = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert current["data"]["state"] == "approved"
    async with engine.new_session() as session:
        assert (await session.get(GuardTask, task_id)).state == "cancelled"


async def test_external_restore_completes_disabled_policy_release(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    await store.save_policy(guard_group, {"bot_join_approval_enabled": False})
    restored = bot_member(helper_bot, status="restricted", can_send_messages=True)
    assert await bot_approval.external_permission_change(guard_group, restored)
    assert await bot_approval.approval_status(guard_group, helper_bot.id) is None
    async with engine.new_session() as session:
        release = await session.scalar(
            select(GuardTask).where(
                GuardTask.group_id == guard_group,
                GuardTask.kind == "bot_release",
            )
        )
        assert release.state == "cancelled"


async def test_delayed_leave_does_not_clear_new_generation(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    first = guard_message().date
    await runtime.member_joined(guard_bot, chat, helper_bot, first)
    await runtime.member_left(guard_group, helper_bot.id, first)
    second = first.replace(microsecond=0)
    # A later rejoin receives a distinct generation.
    second = second.replace(second=second.second + 1)
    await runtime.member_joined(guard_bot, chat, helper_bot, second)
    current = await bot_approval.approval_status(guard_group, helper_bot.id)
    await runtime.member_left(guard_group, helper_bot.id, first)
    assert (await bot_approval.approval_status(guard_group, helper_bot.id))["data"][
        "generation"
    ] == current["data"]["generation"]


async def test_old_review_generation_cannot_approve_new_record(
    guard_group, guard_bot, helper_bot, guard_message
):
    chat = Chat(guard_group, "supergroup", title="Test group")
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    old_review = (await store.records(guard_group, "review", enabled=True))[0]
    await runtime.member_left(guard_group, helper_bot.id, guard_message().date)
    await runtime.member_joined(guard_bot, chat, helper_bot, guard_message().date)
    with pytest.raises(ValueError):
        await reviews.decide(
            guard_bot,
            guard_group,
            old_review["id"],
            "approve_bot",
            "old",
            actor_id=1,
        )
    assert (await bot_approval.approval_status(guard_group, helper_bot.id))["data"][
        "state"
    ] == "pending"


async def test_join_request_approval_preapproves_bot(
    guard_group, guard_bot, helper_bot, guard_message
):
    await store.save_policy(
        guard_group,
        {"join_requests_enabled": True, "join_auto_approve": True},
    )
    request = SimpleNamespace(
        chat=Chat(guard_group, "supergroup", title="Test group"),
        from_user=helper_bot,
        date=guard_message().date,
    )
    await verification.join_request(
        SimpleNamespace(chat_join_request=request), SimpleNamespace(bot=guard_bot)
    )
    guard_bot.approve_chat_join_request.assert_awaited_once_with(
        guard_group, helper_bot.id
    )
    assert (await bot_approval.approval_status(guard_group, helper_bot.id))["data"][
        "state"
    ] == "approved"
    await runtime.member_joined(
        guard_bot, request.chat, helper_bot, request.date
    )
    assert guard_bot.restrict_chat_member.await_count == 0


async def test_duplicate_review_creation_does_not_resend_notification(
    guard_group, guard_bot
):
    payload = {
        "kind": "bot_join",
        "user_id": 777,
        "is_bot": True,
        "name": "Duplicate",
        "generation": "generation-1",
        "reason": "待批准",
    }
    first = await reviews.create(
        guard_group, "bot_join:777:generation-1", payload, guard_bot
    )
    second = await reviews.create(
        guard_group, "bot_join:777:generation-1", payload, guard_bot
    )
    assert first["id"] == second["id"]
    guard_bot.send_message.assert_awaited_once()


async def test_ai_moderation_waits_for_release_completion(
    guard_group, guard_bot, helper_bot
):
    await store.save_policy(
        guard_group,
        {
            "bot_join_approval_enabled": False,
            "bot_moderation_enabled": True,
        },
    )
    await store.put_record(
        guard_group,
        "bot_approval",
        str(helper_bot.id),
        {
            "user_id": helper_bot.id,
            "generation": "release-generation",
            "state": "approved",
            "release_pending": True,
            "restricted": False,
            "managed": False,
        },
    )
    assert not await bot_approval.allowed_for_moderation(
        guard_bot, guard_group, helper_bot.id
    )


async def test_worker_recovery_rebuilds_missing_bot_review(
    guard_group, guard_bot, helper_bot
):
    await store.put_record(
        guard_group,
        "bot_approval",
        str(helper_bot.id),
        {
            "user_id": helper_bot.id,
            "name": helper_bot.full_name,
            "username": helper_bot.username,
            "generation": "missing-review-generation",
            "state": "pending",
            "restricted": False,
            "managed": False,
        },
    )
    await worker.Worker(guard_bot).recover()
    record = await bot_approval.approval_status(guard_group, helper_bot.id)
    assert record["data"].get("review_id")
    reviews_for_bot = [
        row
        for row in await store.records(guard_group, "review", enabled=True)
        if row["data"].get("user_id") == helper_bot.id
    ]
    assert len(reviews_for_bot) == 1
