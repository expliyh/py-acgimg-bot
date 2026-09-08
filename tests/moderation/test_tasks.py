"""Persisted task recovery, scheduling boundaries and worker cancellation."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update
from telegram import User
from telegram.error import BadRequest, TimedOut

from models import GroupGuardPendingVerification as Pending
from models import GuardEvent, GuardTask
from registries import engine
from services.moderation import actions, ai, store, verification, worker
from services.moderation.schemas import ActionRequest, AIVerdict, Content, Policy


def utc_naive(year, month, day, hour):
    """The persisted scheduler contract uses naive UTC, never local time."""
    return datetime(year, month, day, hour, tzinfo=timezone.utc).replace(tzinfo=None)


async def jobs():
    async with engine.new_session() as session:
        return [
            store.dump(row) for row in (await session.scalars(select(GuardTask))).all()
        ]


@pytest.mark.parametrize("lost_rights", [False, True])
async def test_rejected_second_mute_preserves_original_expiration(
    guard_group, guard_bot, lost_rights
):
    first = await actions.execute(
        guard_bot, guard_group,
        ActionRequest(action="mute", user_id=2, request_id="original-mute"),
    )
    original = await store.record(guard_group, "restriction", "2")
    assert first["status"] == "success"
    if lost_rights:
        guard_bot.rights["can_restrict_members"] = False
    second = await actions.execute(
        guard_bot, guard_group,
        ActionRequest(action="mute", user_id=2, request_id="second-mute"),
    )
    assert second["status"] == "failed"
    assert await store.record(guard_group, "restriction", "2") == original
    guard_bot.restrict_chat_member.assert_awaited_once()
    guard_bot.rights["can_restrict_members"] = True
    await worker.Worker(guard_bot).dispatch((await jobs())[0])
    assert await store.record(guard_group, "restriction", "2") is None
    assert guard_bot.restrict_chat_member.await_count == 2


async def test_expiration_rechecks_restriction_after_entering_action_lock(
    guard_group, guard_bot, monkeypatch
):
    execute = actions.execute
    await execute(
        guard_bot, guard_group,
        ActionRequest(action="mute", user_id=2, request_id="first"),
    )
    old_job = (await jobs())[0]
    replacement = None

    async def replace_before_lock(bot, group_id, request, **kwargs):
        nonlocal replacement
        await execute(
            bot, group_id,
            ActionRequest(action="unmute", user_id=2, request_id="manual-release"),
        )
        replacement = await execute(
            bot, group_id,
            ActionRequest(action="mute", user_id=2, request_id="replacement"),
        )
        guard_bot.restrict_chat_member.reset_mock()
        return await execute(bot, group_id, request, **kwargs)

    monkeypatch.setattr(actions, "execute", replace_before_lock)
    await worker.Worker(guard_bot).dispatch(old_job)
    guard_bot.restrict_chat_member.assert_not_awaited()
    current = await store.record(guard_group, "restriction", "2")
    assert current["data"]["event_id"] == replacement["id"]


async def test_restart_processes_expired_verification_once(guard_group, guard_bot):
    await verification.start(
        guard_bot, guard_group, User(2, "New", False), "Group", Policy()
    )
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        row.expires_at = store.now() - timedelta(seconds=1)
        await session.commit()
    restarted = worker.Worker(guard_bot)
    await restarted.recover()
    await restarted.recover()
    await restarted.tick()
    await restarted.tick()
    guard_bot.ban_chat_member.assert_awaited_once()
    assert guard_bot.ban_chat_member.call_args.args == (guard_group, 2)
    ban_until = guard_bot.ban_chat_member.call_args.kwargs["until_date"]
    assert (
        datetime.now(timezone.utc)
        < ban_until
        <= datetime.now(timezone.utc) + timedelta(minutes=1)
    )
    guard_bot.unban_chat_member.assert_awaited_once_with(
        guard_group, 2, only_if_banned=True
    )
    async with engine.new_session() as session:
        assert (await session.get(Pending, (guard_group, 2))).state == "removed"


async def test_old_timeout_cannot_remove_member_in_new_verification(
    guard_group, guard_bot
):
    await verification.start(
        guard_bot, guard_group, User(2, "New", False), "Group", Policy()
    )
    original = next(row for row in await jobs() if row["kind"] == "verify")
    assert (
        await verification.finish(guard_bot, guard_group, 2, original["data"]["token"])
        == "验证通过"
    )
    await verification.start(
        guard_bot, guard_group, User(2, "New", False), "Group", Policy()
    )
    await worker.Worker(guard_bot).dispatch(original)
    guard_bot.ban_chat_member.assert_not_awaited()
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        assert row.state == "pending"
        assert row.token != original["data"]["token"]


async def test_old_unmute_task_cannot_release_new_restriction(guard_group, guard_bot):
    async def execute(action, request_id):
        return await actions.execute(
            guard_bot,
            guard_group,
            ActionRequest(action=action, user_id=2, request_id=request_id),
        )

    await execute("mute", "old")
    old_job = next(row for row in await jobs() if row["kind"] == "unmute")
    await execute("unmute", "release")
    new_mute = await execute("mute", "new")
    guard_bot.restrict_chat_member.reset_mock()
    await worker.Worker(guard_bot).dispatch(old_job)
    guard_bot.restrict_chat_member.assert_not_awaited()
    assert (await store.record(guard_group, "restriction", "2"))["data"][
        "event_id"
    ] == new_mute["id"]


@pytest.mark.parametrize(
    "late_seconds,state,send_count", [(299, "done", 1), (301, "missed", 0)]
)
async def test_single_announcement_five_minute_grace(
    guard_group, guard_bot, monkeypatch, late_seconds, state, send_count
):
    clock = utc_naive(2026, 9, 7, 12)
    monkeypatch.setattr(store, "now", lambda: clock)
    await worker.save_content(
        guard_group,
        Content(
            kind="announcement",
            name="one",
            text="scheduled",
            repeat="once",
            due_at=(clock - timedelta(seconds=late_seconds)).replace(
                tzinfo=timezone.utc
            ),
        ),
    )
    await worker.Worker(guard_bot).tick()
    rows = await jobs()
    assert len(rows) == 1
    assert rows[0]["state"] == state
    assert guard_bot.send_message.await_count == send_count


@pytest.mark.parametrize(
    "due,repeat,clock,expected",
    [
        (
            utc_naive(2026, 3, 7, 14),
            "daily",
            utc_naive(2026, 3, 8, 12),
            utc_naive(2026, 3, 8, 13),
        ),
        (
            utc_naive(2026, 10, 25, 13),
            "weekly",
            utc_naive(2026, 11, 1, 13),
            utc_naive(2026, 11, 1, 14),
        ),
        (
            utc_naive(2026, 1, 1, 1),
            "daily",
            utc_naive(2026, 1, 10, 2),
            utc_naive(2026, 1, 11, 1),
        ),
    ],
)
def test_recurrence_keeps_local_hour_across_dst_and_skips_missed_dates(
    due, repeat, clock, expected
):
    assert worker.next_occurrence(due, repeat, "America/New_York", clock) == expected


async def test_edit_cancels_previously_claimed_announcement(guard_group, guard_bot):
    value = Content(
        kind="announcement",
        name="daily",
        text="old",
        due_at=datetime.now(timezone.utc),
        repeat="daily",
    )
    await worker.save_content(guard_group, value)
    old_job = (await jobs())[0]
    await worker.set_state(old_job["id"], "running")
    await worker.save_content(guard_group, value.model_copy(update={"text": "new"}))
    await worker.Worker(guard_bot).dispatch(old_job)
    guard_bot.send_message.assert_not_awaited()
    await worker.Worker(guard_bot).tick()
    guard_bot.send_message.assert_awaited_once_with(guard_group, "new")
    assert (
        next(row for row in await jobs() if row["id"] == old_job["id"])["state"]
        == "cancelled"
    )


async def test_ambiguous_send_is_never_automatically_retried(guard_group, guard_bot):
    await worker.save_content(
        guard_group,
        Content(
            kind="announcement",
            name="once",
            text="hello",
            due_at=datetime.now(timezone.utc),
        ),
    )
    guard_bot.send_message.side_effect = TimedOut()
    await worker.Worker(guard_bot).tick()
    restarted = worker.Worker(guard_bot)
    await restarted.recover()
    await restarted.tick()
    guard_bot.send_message.assert_awaited_once()
    assert (await jobs())[0]["state"] == "uncertain"


async def test_deterministic_telegram_task_error_is_failed(guard_group, guard_bot):
    task_id = await store.task(guard_group, "delete", store.now(), {"message_id": 404})
    job = next(row for row in await jobs() if row["id"] == task_id)
    guard_bot.delete_message.side_effect = BadRequest("message not found")

    await worker.Worker(guard_bot).dispatch(job)

    assert (
        next(row for row in await jobs() if row["id"] == task_id)["state"] == "failed"
    )


async def test_recurring_announcement_continues_after_ambiguous_send(
    guard_group, guard_bot, monkeypatch
):
    clock = utc_naive(2026, 9, 7, 12)
    monkeypatch.setattr(store, "now", lambda: clock)
    await worker.save_content(
        guard_group,
        Content(
            kind="announcement",
            name="daily",
            text="hello",
            due_at=clock.replace(tzinfo=timezone.utc),
            repeat="daily",
        ),
    )
    guard_bot.send_message.side_effect = TimedOut()
    await worker.Worker(guard_bot).tick()

    rows = await jobs()
    assert sorted(row["state"] for row in rows) == ["pending", "uncertain"]
    following = next(row for row in rows if row["state"] == "pending")
    assert following["due_at"] == utc_naive(2026, 9, 8, 12)
    guard_bot.send_message.assert_awaited_once_with(guard_group, "hello")


@pytest.mark.parametrize("successor_exists", [False, True])
async def test_recovery_continues_claimed_recurring_announcement_without_resend(
    guard_group, guard_bot, monkeypatch, successor_exists
):
    clock = utc_naive(2026, 9, 7, 12)
    monkeypatch.setattr(store, "now", lambda: clock)
    await worker.save_content(
        guard_group,
        Content(
            kind="announcement",
            name="daily",
            text="hello",
            due_at=clock.replace(tzinfo=timezone.utc),
            repeat="daily",
        ),
    )
    claimed = (await jobs())[0]
    await worker.set_state(claimed["id"], "running")
    if successor_exists:
        await store.task(
            guard_group,
            "announcement",
            utc_naive(2026, 9, 8, 12),
            claimed["data"],
        )

    restarted = worker.Worker(guard_bot)
    await restarted.recover()
    await restarted.recover()

    rows = await jobs()
    assert (
        next(row for row in rows if row["id"] == claimed["id"])["state"] == "uncertain"
    )
    pending = [row for row in rows if row["state"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["due_at"] == utc_naive(2026, 9, 8, 12)
    guard_bot.send_message.assert_not_awaited()


async def test_ai_concurrency_does_not_block_cleanup_and_stop_cancels_calls(
    guard_group, guard_bot, monkeypatch
):
    started = asyncio.Event()
    release = asyncio.Event()
    active, cancelled = set(), set()

    async def slow_classifier(bot, job):
        active.add(job["id"])
        if len(active) == 2:
            started.set()
        try:
            await release.wait()
        finally:
            cancelled.add(job["id"])

    monkeypatch.setattr(ai, "process", slow_classifier)
    for _ in range(4):
        await store.task(guard_group, "ai", store.now(), {})
    running = worker.Worker(guard_bot)
    try:
        await running.tick()
        await asyncio.wait_for(started.wait(), timeout=5)
        await store.task(guard_group, "delete", store.now(), {"message_id": 50})
        await running.tick()
        assert len(active) == 2
        guard_bot.delete_message.assert_awaited_once_with(guard_group, 50)
        states = [row["state"] for row in await jobs() if row["kind"] == "ai"]
        assert states.count("running") == 2 and states.count("pending") == 2
    finally:
        await running.stop()
    assert cancelled == active
    await worker.Worker(guard_bot).recover()
    assert sum(row["state"] == "pending" for row in await jobs()) == 4


async def test_recovery_retries_ai_classification_before_external_actions(
    guard_group, guard_bot, guard_ai_job, monkeypatch
):
    job = await guard_ai_job()
    task_id = await store.task(guard_group, "ai", store.now(), job["data"])
    await worker.set_state(task_id, "running", "classifying")
    await store.event(
        guard_group,
        "ai",
        incident=f"ai:10:{job['data']['version']}",
        status="running",
        message_id=10,
    )

    restarted = worker.Worker(guard_bot)
    await restarted.recover()
    async with engine.new_session() as session:
        recovered = await session.get(GuardTask, task_id)
        assert recovered.state == "pending"
        retry = store.dump(recovered)
        assert await session.scalar(
            select(GuardEvent).where(GuardEvent.action == "ai")
        ) is None

    classifier = AsyncMock(
        return_value=(
            AIVerdict(category="safe", confidence=1, reason="safe"),
            {"total_tokens": 2},
        )
    )
    monkeypatch.setattr(ai, "classify", classifier)
    await worker.set_state(task_id, "running", "classifying")
    await restarted.dispatch(retry)

    classifier.assert_awaited_once()
    async with engine.new_session() as session:
        assert (await session.get(GuardTask, task_id)).state == "done"
        event = await session.scalar(
            select(GuardEvent).where(GuardEvent.action == "ai")
        )
        assert event.status == "success"


@pytest.mark.parametrize("phase", ["moderating", "", None])
async def test_recovery_preserves_ai_ambiguity_after_moderation_begins(
    guard_group, guard_bot, guard_ai_job, phase
):
    job = await guard_ai_job()
    task_id = await store.task(guard_group, "ai", store.now(), job["data"])
    await worker.set_state(task_id, "running", "moderating")
    async with engine.new_session() as session:
        await session.execute(
            update(GuardTask).where(GuardTask.id == task_id).values(result=phase)
        )
        await session.commit()
    await store.event(
        guard_group,
        "ai",
        incident=f"ai:10:{job['data']['version']}",
        status="running",
        message_id=10,
    )

    await worker.Worker(guard_bot).recover()
    async with engine.new_session() as session:
        assert (await session.get(GuardTask, task_id)).state == "uncertain"
        event = await session.scalar(
            select(GuardEvent).where(GuardEvent.action == "ai")
        )
        assert event.status == "uncertain"


async def test_ai_persists_moderation_phase_before_punishment(
    guard_group, guard_bot, guard_ai_job, monkeypatch
):
    job = await guard_ai_job()
    task_id = await store.task(guard_group, "ai", store.now(), job["data"])
    await worker.set_state(task_id, "running", "classifying")
    job["id"] = task_id
    monkeypatch.setattr(
        ai,
        "classify",
        AsyncMock(
            return_value=(
                AIVerdict(category="spam", confidence=1, reason="spam"),
                {},
            )
        ),
    )
    observed = None

    async def punish(*args, **kwargs):
        nonlocal observed
        async with engine.new_session() as session:
            observed = (await session.get(GuardTask, task_id)).result
        return []

    monkeypatch.setattr(ai.actions, "punish", punish)
    assert await ai.process(guard_bot, job) == "punish"
    assert observed == "moderating"


async def test_retention_preserves_effective_warnings_and_uncertain_tasks(
    guard_group, guard_bot
):
    await store.save_policy(guard_group, {"log_days": 7, "warning_days": 14})
    recent, _ = await store.event(guard_group, "warn", user_id=2)
    expired, _ = await store.event(guard_group, "warn", user_id=2)
    done = await store.task(guard_group, "delete", store.now(), {})
    failed = await store.task(guard_group, "delete", store.now(), {})
    uncertain = await store.task(guard_group, "announcement", store.now(), {})
    await worker.set_state(done, "done")
    await worker.set_state(failed, "failed")
    await worker.set_state(uncertain, "uncertain")
    async with engine.new_session() as session:
        await session.execute(
            update(GuardEvent)
            .where(GuardEvent.id == recent["id"])
            .values(created_at=store.now() - timedelta(days=8))
        )
        await session.execute(
            update(GuardEvent)
            .where(GuardEvent.id == expired["id"])
            .values(created_at=store.now() - timedelta(days=15))
        )
        await session.execute(
            update(GuardTask)
            .where(GuardTask.id.in_([done, failed]))
            .values(
                created_at=store.now() - timedelta(days=15),
                completed_at=store.now() - timedelta(days=15),
            )
        )
        await session.execute(
            update(GuardTask)
            .where(GuardTask.id == uncertain)
            .values(created_at=store.now() - timedelta(days=15))
        )
        await session.commit()
    await worker.Worker(guard_bot).cleanup()
    assert [row["id"] for row in await store.warnings(guard_group, 2)] == [recent["id"]]
    assert [row["id"] for row in await jobs()] == [uncertain]


async def test_retention_starts_when_a_long_scheduled_task_finishes(
    guard_group, guard_bot
):
    await store.save_policy(guard_group, {"log_days": 7})
    task_id = await store.task(
        guard_group,
        "announcement",
        store.now() + timedelta(days=30),
        {},
    )
    async with engine.new_session() as session:
        await session.execute(
            update(GuardTask)
            .where(GuardTask.id == task_id)
            .values(created_at=store.now() - timedelta(days=30))
        )
        await session.commit()

    await worker.set_state(task_id, "done")
    await worker.Worker(guard_bot).cleanup()

    task = next(row for row in await jobs() if row["id"] == task_id)
    assert task["state"] == "done"
    assert task["completed_at"] is not None
