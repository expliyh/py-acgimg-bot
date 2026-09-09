"""Recovery paths for rate limits, retained verifications and migrated task snapshots."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text, update
from telegram import Chat, User
from telegram.error import RetryAfter

from models import GroupGuardPendingVerification as Pending
from models import GuardEvent, GuardTask
from registries import engine
from services import schema_migrator
from services.moderation import actions, ai, reviews, runtime, store, verification, worker
from services.moderation.schemas import ActionRequest, AIVerdict, Content


@pytest.mark.parametrize("notification_fails", [False, True])
async def test_rate_limited_approval_has_one_actionable_review(
    guard_group, guard_bot, notification_fails
):
    await store.save_policy(guard_group, {
        "join_requests_enabled": True, "join_auto_approve": True,
    })
    guard_bot.approve_chat_join_request.side_effect = RetryAfter(30)
    if notification_fails:
        guard_bot.send_message.side_effect = RetryAfter(30)
    request = SimpleNamespace(
        chat=Chat(guard_group, "supergroup"), from_user=User(2, "Applicant", False),
        date=datetime.now(timezone.utc),
    )
    for _ in range(2):
        await verification.join_request(
            SimpleNamespace(chat_join_request=request), SimpleNamespace(bot=guard_bot)
        )
    guard_bot.approve_chat_join_request.assert_awaited_once()
    records = await store.records(guard_group, "review")
    assert len(records) == 1 and records[0]["data"]["state"] == "pending"
    async with engine.new_session() as session:
        receipt = await session.scalar(select(GuardEvent).where(GuardEvent.action == "join_request"))
        assert receipt.data["review"] and receipt.data["auto_approve"] == "rate_limited"
        assert not receipt.data.get("approved")
    result = await reviews.decide(
        guard_bot, guard_group, records[0]["id"], "approve_join", "retry", actor_id=1
    )
    assert result["data"]["state"] == "pending" and result["enabled"]
    guard_bot.approve_chat_join_request.side_effect = None
    result = await reviews.decide(
        guard_bot, guard_group, records[0]["id"], "approve_join", "retry", actor_id=1
    )
    assert result["data"]["state"] == "resolved"
    assert guard_bot.approve_chat_join_request.await_count == 3


async def test_cleanup_uses_completion_time_and_preserves_unresolved_states(
    guard_group, guard_bot, monkeypatch
):
    clock = store.now()
    monkeypatch.setattr(store, "now", lambda: clock)
    await store.save_policy(guard_group, {"log_days": 7})
    states = sorted(Pending.TERMINAL_STATES) + ["pending", "preparing", "processing", "restricted", "uncertain"]
    async with engine.new_session() as session:
        for group_id in (guard_group, guard_group - 1):
            for i, state in enumerate(states, 1):
                session.add(Pending(
                    group_id=group_id, user_id=i, token=store.uid(), state=state,
                    created_at=clock - timedelta(days=180),
                    expires_at=clock - timedelta(days=179),
                    completed_at=clock - timedelta(days=8),
                ))
        for i, completion in enumerate((clock, clock - timedelta(days=7)), 100):
            session.add(Pending(
                group_id=guard_group, user_id=i, token=store.uid(), state="passed",
                expires_at=clock - timedelta(days=180), completed_at=completion,
            ))
        await session.commit()
    # There are no events or tasks: verification rows alone must discover the group.
    await worker.Worker(guard_bot).cleanup()
    async with engine.new_session() as session:
        rows = (await session.scalars(select(Pending))).all()
    assert {row.user_id for row in rows if row.group_id == guard_group} == set(range(6, 11)) | {100, 101}
    assert len([row for row in rows if row.group_id != guard_group]) == len(states)


async def test_verification_completion_resets_for_a_new_join(guard_group, guard_bot):
    settings = await store.policy(guard_group)
    member = User(2, "Member", False)
    await verification.start(guard_bot, guard_group, member, "Group", settings)
    async with engine.new_session() as session:
        token = (await session.get(Pending, (guard_group, 2))).token
    await verification.finish(guard_bot, guard_group, 2, token)
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        assert row.state == "passed" and row.completed_at is not None
    await verification.start(guard_bot, guard_group, member, "Group", settings)
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        assert row.token != token and row.completed_at is None
    await actions.execute(guard_bot, guard_group, ActionRequest(
        action="unmute", user_id=2, request_id="manual-recovery",
    ))
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        assert row.state == "cancelled" and row.completed_at is not None


async def test_verification_completion_migration_preserves_all_states():
    table = schema_migrator._quote(Pending.__tablename__)
    states = sorted(Pending.TERMINAL_STATES) + ["pending", "restricted", "uncertain"]
    async with engine.engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table}"))
        await conn.execute(text(f"CREATE TABLE {table} (state VARCHAR(24) PRIMARY KEY)"))
        await conn.execute(text(f"INSERT INTO {table} (state) VALUES (:state)"), [{"state": s} for s in states])
        await schema_migrator._add_guard_verification_completion_time(conn)
        before = dict((await conn.execute(text(f"SELECT state, completed_at FROM {table}"))).all())
        await schema_migrator._add_guard_verification_completion_time(conn)
        after = dict((await conn.execute(text(f"SELECT state, completed_at FROM {table}"))).all())
    assert before == after
    assert {s for s, completion in after.items() if completion} == Pending.TERMINAL_STATES


async def test_verification_timeout_preserves_an_existing_timed_mute(
    guard_group, guard_bot
):
    await store.save_policy(guard_group, {"kick_on_timeout": False})
    user = User(2, "Member", False)
    await verification.start(
        guard_bot, guard_group, user, "Group", await store.policy(guard_group)
    )
    original_lookup = guard_bot.get_chat_member.side_effect

    async def restricted_member(group_id, user_id):
        if user_id == 2:
            return SimpleNamespace(
                status="restricted", user=user,
                until_date=datetime.fromtimestamp(0, timezone.utc),
            )
        return await original_lookup(group_id, user_id)

    guard_bot.get_chat_member.side_effect = restricted_member
    await actions.execute(guard_bot, guard_group, ActionRequest(
        action="mute", user_id=2, request_id="moderator-mute",
    ))
    restriction = await store.record(guard_group, "restriction", "2")
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        row.expires_at = store.now() - timedelta(seconds=1)
        token = row.token
        await session.commit()
    await verification.finish(guard_bot, guard_group, 2, token, expired=True)
    assert await store.record(guard_group, "restriction", "2") == restriction
    async with engine.new_session() as session:
        job = store.dump(await session.scalar(select(GuardTask).where(GuardTask.kind == "unmute")))
    await worker.Worker(guard_bot).dispatch(job)
    assert guard_bot.restrict_chat_member.call_args.args[2].can_send_messages is False
    assert await store.record(guard_group, "restriction", "2") is None
    result = await actions.execute(guard_bot, guard_group, ActionRequest(
        action="unmute", user_id=2, request_id="release-verification",
    ))
    assert result["status"] == "success"
    assert guard_bot.restrict_chat_member.call_args.args[2].can_send_messages is True


@pytest.mark.parametrize("state", ["pending", "running"])
@pytest.mark.parametrize("kind", ["unmute", "verify", "announcement", "delete", "ai"])
async def test_migrated_task_uses_persisted_group_instead_of_snapshot(
    guard_group, guard_bot, guard_ai_job, monkeypatch, state, kind
):
    if kind == "unmute":
        await actions.execute(guard_bot, guard_group, ActionRequest(
            action="mute", user_id=2, duration=60, request_id="before-upgrade",
        ))
    elif kind == "verify":
        await verification.start(
            guard_bot, guard_group, User(2, "Member", False), "Group", await store.policy(guard_group)
        )
        async with engine.new_session() as session:
            await session.execute(update(Pending).values(expires_at=store.now() - timedelta(seconds=1)))
            await session.commit()
    elif kind == "announcement":
        await worker.save_content(guard_group, Content(
            kind=kind, name="notice", text="notice", due_at=datetime.now(timezone.utc),
        ))
    elif kind == "delete":
        await store.task(guard_group, kind, store.now(), {"message_id": 10})
    else:
        job = await guard_ai_job()
        await store.task(guard_group, kind, store.now(), job["data"])
        monkeypatch.setattr(ai, "classify", AsyncMock(return_value=(
            AIVerdict(category="spam", confidence=1, reason="spam"), {}
        )))
    async with engine.new_session() as session:
        row = await session.scalar(select(GuardTask).where(GuardTask.kind == kind))
        row.state = state
        snapshot = store.dump(row)
        await session.commit()
    new_id = guard_group - 1
    await runtime.migrate(guard_group, new_id)
    guard_bot.reset_mock()
    await worker.Worker(guard_bot).dispatch(snapshot)
    method = {
        "unmute": guard_bot.restrict_chat_member,
        "verify": guard_bot.ban_chat_member,
        "announcement": guard_bot.send_message,
        "delete": guard_bot.delete_message,
        "ai": guard_bot.delete_message,
    }[kind]
    assert method.await_count > 0
    assert all(call.args[0] == new_id for call in method.call_args_list)
    async with engine.new_session() as session:
        row = await session.get(GuardTask, snapshot["id"])
        assert row.state == "done" and row.group_id == new_id
    if kind == "unmute":
        assert await store.record(new_id, "restriction", "2") is None


@pytest.mark.parametrize("cancel_migration", [False, True])
async def test_migration_waits_for_active_task_and_preserves_its_result(
    guard_group, guard_bot, cancel_migration
):
    started, release = asyncio.Event(), asyncio.Event()

    async def sending(*args):
        started.set()
        await release.wait()

    guard_bot.delete_message.side_effect = sending
    task_id = await store.task(guard_group, "delete", store.now(), {"message_id": 10})
    runner = asyncio.create_task(worker.Worker(guard_bot).tick())
    await asyncio.wait_for(started.wait(), 5)
    migration = asyncio.create_task(runtime.migrate(guard_group, guard_group - 1))
    try:
        # A second, independent group can continue while migration waits.
        other = await store.task(guard_group - 2, "announcement", store.now(), {"name": "missing"})
        async with engine.new_session() as session:
            snapshot = store.dump(await session.get(GuardTask, other))
        await asyncio.wait_for(worker.Worker(guard_bot).dispatch(snapshot), 5)
        assert not migration.done()
        if cancel_migration:
            migration.cancel()
            await asyncio.gather(migration, return_exceptions=True)
        release.set()
        if cancel_migration:
            await asyncio.wait_for(runner, 5)
            await asyncio.wait_for(runtime.migrate(guard_group, guard_group - 1), 5)
        else:
            await asyncio.wait_for(asyncio.gather(runner, migration), 5)
    finally:
        release.set()
        for task in (runner, migration):
            if not task.done():
                task.cancel()
        await asyncio.gather(runner, migration, return_exceptions=True)
    async with engine.new_session() as session:
        row = await session.get(GuardTask, task_id)
        assert row.state == "done" and row.group_id == guard_group - 1
    guard_bot.delete_message.assert_awaited_once()
