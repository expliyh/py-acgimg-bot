"""Departures must retire old member state; restarts must reuse durable timers."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from telegram import ChatMemberRestricted, Update
from telegram.error import NetworkError

from models import GroupGuardPendingVerification as Pending
from models import GuardTask
from registries import engine
from services.moderation import actions, runtime, store, verification, worker
from services.moderation.schemas import ActionRequest


def restricted(user, *, is_member=True):
    return {
        "user": user.to_dict(),
        "status": "restricted",
        "is_member": is_member,
        "until_date": 0,
        **{
            name: False
            for name in ChatMemberRestricted.__slots__
            if name.startswith("can_")
        },
    }


def membership(message, bot, old, new, *, actor=2, date=None):
    return Update.de_json(
        {
            "update_id": 200,
            "chat_member": {
                "chat": message.chat.to_dict(),
                "from": {"id": actor, "first_name": "Actor", "is_bot": actor == bot.id},
                "date": int((date or message.date).timestamp()),
                "old_chat_member": old,
                "new_chat_member": new,
            },
        },
        bot,
    )


async def test_failed_join_setup_remains_retryable_on_duplicate_update(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"verification_enabled": True})
    message = guard_message()
    get_member = guard_bot.get_chat_member.side_effect
    first_lookup = True

    async def flaky_get_member(chat_id, user_id):
        nonlocal first_lookup
        if first_lookup:
            first_lookup = False
            raise NetworkError("temporary lookup failure")
        return await get_member(chat_id, user_id)

    guard_bot.get_chat_member.side_effect = flaky_get_member
    await runtime.member_joined(
        guard_bot, message.chat, message.from_user, message.date
    )
    assert await store.record(guard_group, "join_seen", "2") is None
    async with engine.new_session() as session:
        assert await session.get(Pending, (guard_group, 2)) is None

    await runtime.member_joined(
        guard_bot, message.chat, message.from_user, message.date
    )
    assert await store.record(guard_group, "join_seen", "2")
    async with engine.new_session() as session:
        assert (await session.get(Pending, (guard_group, 2))).state == "pending"
    guard_bot.restrict_chat_member.assert_awaited_once()


async def test_concurrent_duplicate_joins_start_one_verification(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"verification_enabled": True})
    message = guard_message()
    await asyncio.gather(
        runtime.member_joined(
            guard_bot, message.chat, message.from_user, message.date
        ),
        runtime.member_joined(
            guard_bot, message.chat, message.from_user, message.date
        ),
    )
    guard_bot.restrict_chat_member.assert_awaited_once()
    guard_bot.send_message.assert_awaited_once()


@pytest.mark.parametrize(
    "state", ["pending", "preparing", "processing", "restricted", "uncertain"]
)
async def test_external_permissions_retire_all_unresolved_verifications(
    guard_group, guard_bot, guard_message, state
):
    message = guard_message()
    await verification.start(
        guard_bot, guard_group, message.from_user, "Group", await store.policy(guard_group)
    )
    async with engine.new_session() as session:
        row = await session.get(Pending, (guard_group, 2))
        row.state = state
        token = row.token
        snapshot = row.original_permissions
        await session.commit()
    await store.put_record(guard_group, "restriction", "2", {
        "event_id": token, "original": snapshot, "state": "active",
    })
    original = restricted(message.from_user)
    guard_bot.members[2] = ChatMemberRestricted.de_json(
        original | {"can_send_photos": True}, guard_bot
    )
    await runtime.membership(
        membership(message, guard_bot, original,
                   original | {"can_send_photos": True}, actor=1,
                   # Telegram membership updates have second precision. Make
                   # this synthetic external edit unambiguously follow the
                   # verification setup even on a slow CI runner.
                   date=message.date + timedelta(seconds=1)),
        SimpleNamespace(bot=guard_bot),
    )
    async with engine.new_session() as session:
        assert (await session.get(Pending, (guard_group, 2))).state == "external"
    assert await store.record(guard_group, "restriction", "2") is None
    guard_bot.restrict_chat_member.reset_mock()
    result = await actions.execute(
        guard_bot, guard_group,
        ActionRequest(action="unmute", user_id=2, request_id="after-external-edit"),
    )
    assert result["status"] == "failed"
    guard_bot.restrict_chat_member.assert_not_awaited()


async def timers(group_id):
    async with engine.new_session() as session:
        return [
            store.dump(row)
            for row in (
                await session.scalars(
                    select(GuardTask).where(
                        GuardTask.group_id == group_id,
                        GuardTask.kind.in_(["verify", "unmute"]),
                    )
                )
            ).all()
        ]


@pytest.mark.parametrize(
    "new_status,actor", [("left", 2), ("kicked", 1), ("kicked", 999), ("restricted", 2)]
)
async def test_departure_retires_mute_and_allows_future_moderation(
    guard_group, guard_bot, guard_message, new_status, actor
):
    message = guard_message()
    await actions.execute(
        guard_bot,
        guard_group,
        ActionRequest(action="warn", user_id=2, request_id="warning"),
    )
    await actions.execute(
        guard_bot,
        guard_group,
        ActionRequest(action="mute", user_id=2, request_id="old-mute"),
    )
    old_job = (await timers(guard_group))[0]
    other_job = await store.task(
        guard_group + 1, "unmute", store.now(), old_job["data"]
    )
    new = (
        restricted(message.from_user, is_member=False)
        if new_status == "restricted"
        else {
            "user": message.from_user.to_dict(),
            "status": new_status,
            "until_date": 0,
        }
    )
    departed = membership(
        message, guard_bot, restricted(message.from_user), new, actor=actor
    )
    guard_bot.restrict_chat_member.reset_mock()
    await runtime.membership(departed, SimpleNamespace(bot=guard_bot))
    await runtime.membership(departed, SimpleNamespace(bot=guard_bot))
    assert await store.record(guard_group, "restriction", "2") is None
    assert (await timers(guard_group))[0]["state"] == "cancelled"
    assert len(await store.warnings(guard_group, 2)) == 1
    async with engine.new_session() as session:
        assert (await session.get(GuardTask, other_job)).state == "pending"
    guard_bot.restrict_chat_member.assert_not_awaited()
    guard_bot.unban_chat_member.assert_not_awaited()

    await runtime.membership(
        membership(
            message,
            guard_bot,
            new,
            {"status": "member", "user": message.from_user.to_dict()},
            date=message.date + timedelta(seconds=2),
        ),
        SimpleNamespace(bot=guard_bot),
    )
    result = await actions.execute(
        guard_bot,
        guard_group,
        ActionRequest(action="mute", user_id=2, request_id="new-mute"),
    )
    assert result["status"] == "success"
    guard_bot.restrict_chat_member.reset_mock()
    await worker.Worker(guard_bot).dispatch(old_job)
    guard_bot.restrict_chat_member.assert_not_awaited()
    assert (await store.record(guard_group, "restriction", "2"))["data"][
        "event_id"
    ] == result["id"]


@pytest.mark.parametrize("signal", ["service", "membership"])
async def test_leave_during_verification_allows_immediate_rejoin(
    guard_group, guard_bot, guard_message, signal
):
    await store.save_policy(guard_group, {"verification_enabled": True})
    message = guard_message()
    context = SimpleNamespace(bot=guard_bot)
    await runtime.member_joined(
        guard_bot, message.chat, message.from_user, message.date
    )
    await actions.execute(
        guard_bot,
        guard_group,
        ActionRequest(action="mute", user_id=2, request_id="old-mute"),
    )
    async with engine.new_session() as session:
        old_token = (await session.get(Pending, (guard_group, 2))).token
    leave_date = message.date + timedelta(seconds=1)
    if signal == "service":
        left = guard_message(
            text=None,
            date=int(leave_date.timestamp()),
            left_chat_member=message.from_user.to_dict(),
        )
        await runtime.preprocess(Update(201, message=left), context)
    else:
        await runtime.membership(
            membership(
                message,
                guard_bot,
                restricted(message.from_user),
                {
                    "status": "left",
                    "user": message.from_user.to_dict(),
                },
                date=leave_date,
            ),
            context,
        )
    async with engine.new_session() as session:
        assert (await session.get(Pending, (guard_group, 2))).state == "cancelled"
    assert all(row["state"] == "cancelled" for row in await timers(guard_group))
    assert await store.record(guard_group, "join_seen", "2") is None
    assert await store.record(guard_group, "restriction", "2") is None

    await runtime.member_joined(
        guard_bot, message.chat, message.from_user, message.date + timedelta(seconds=2)
    )
    async with engine.new_session() as session:
        pending = await session.get(Pending, (guard_group, 2))
        assert pending.state == "pending" and pending.token != old_token
        new_token = pending.token
    before = guard_bot.restrict_chat_member.await_count
    assert await verification.finish(guard_bot, guard_group, 2, new_token) == "验证通过"
    assert guard_bot.restrict_chat_member.await_count == before + 1
    assert (
        await verification.finish(guard_bot, guard_group, 2, old_token, expired=True)
        == "验证已失效或已处理"
    )
    guard_bot.ban_chat_member.assert_not_awaited()


@pytest.mark.parametrize("service_first", [False, True])
async def test_bot_kick_queues_recent_join_and_leave_service_messages(
    guard_group, guard_bot, guard_message, service_first
):
    await store.save_policy(guard_group, {"clean_join_messages_on_kick": True})
    joined = guard_message(
        message_id=40,
        text=None,
        new_chat_members=[guard_message().from_user.to_dict()],
    )
    context = SimpleNamespace(bot=guard_bot)
    await runtime.preprocess(Update(100, message=joined), context)

    left = guard_message(
        message_id=41,
        text=None,
        date=int((joined.date + timedelta(seconds=1)).timestamp()),
        left_chat_member=joined.from_user.to_dict(),
    )
    kicked = membership(
        joined,
        guard_bot,
        {"status": "member", "user": joined.from_user.to_dict()},
        {"status": "kicked", "user": joined.from_user.to_dict(), "until_date": 0},
        actor=guard_bot.id,
        date=joined.date + timedelta(seconds=1),
    )
    if service_first:
        await runtime.preprocess(Update(101, message=left), context)
    await runtime.membership(kicked, context)
    if not service_first:
        await runtime.preprocess(Update(101, message=left), context)

    async with engine.new_session() as session:
        rows = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == guard_group,
                    GuardTask.kind == "delete",
                )
            )
        ).all()
    assert {row.data["message_id"] for row in rows} == {40, 41}
    assert all(row.data["service_cleanup"] for row in rows)


async def test_voluntary_leave_does_not_queue_join_message_cleanup(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"clean_join_messages_on_kick": True})
    joined = guard_message(
        message_id=50,
        text=None,
        new_chat_members=[guard_message().from_user.to_dict()],
    )
    context = SimpleNamespace(bot=guard_bot)
    await runtime.preprocess(Update(110, message=joined), context)
    await runtime.membership(
        membership(
            joined,
            guard_bot,
            {"status": "member", "user": joined.from_user.to_dict()},
            {"status": "left", "user": joined.from_user.to_dict()},
            actor=joined.from_user.id,
            date=joined.date + timedelta(seconds=1),
        ),
        context,
    )
    async with engine.new_session() as session:
        assert not (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == guard_group,
                    GuardTask.kind == "delete",
                )
            )
        ).all()


async def test_delayed_join_service_message_keeps_kick_cleanup_marker(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"clean_join_messages_on_kick": True})
    joined = guard_message(message_id=60)
    context = SimpleNamespace(bot=guard_bot)
    kick_date = joined.date + timedelta(seconds=10)
    await runtime.membership(
        membership(
            joined,
            guard_bot,
            {"status": "member", "user": joined.from_user.to_dict()},
            {"status": "kicked", "user": joined.from_user.to_dict(), "until_date": 0},
            actor=guard_bot.id,
            date=kick_date,
        ),
        context,
    )

    delayed_join = guard_message(
        message_id=60,
        text=None,
        new_chat_members=[joined.from_user.to_dict()],
        date=int(joined.date.timestamp()),
    )
    await runtime.preprocess(Update(120, message=delayed_join), context)
    left = guard_message(
        message_id=61,
        text=None,
        left_chat_member=joined.from_user.to_dict(),
        date=int((kick_date + timedelta(seconds=1)).timestamp()),
    )
    await runtime.preprocess(Update(121, message=left), context)

    async with engine.new_session() as session:
        rows = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == guard_group,
                    GuardTask.kind == "delete",
                )
            )
        ).all()
    assert {row.data["message_id"] for row in rows} == {60, 61}


async def test_rejoin_preserves_queued_service_message_ids(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"clean_join_messages_on_kick": True})
    context = SimpleNamespace(bot=guard_bot)
    base = guard_message()
    user = base.from_user.to_dict()

    async def kick(date):
        await runtime.membership(
            membership(
                base,
                guard_bot,
                {"status": "member", "user": user},
                {"status": "kicked", "user": user, "until_date": 0},
                actor=guard_bot.id,
                date=date,
            ),
            context,
        )

    await runtime.preprocess(
        Update(
            130,
            message=guard_message(
                message_id=70,
                text=None,
                new_chat_members=[user],
                date=int(base.date.timestamp()),
            ),
        ),
        context,
    )
    await kick(base.date + timedelta(seconds=1))
    await runtime.preprocess(
        Update(
            131,
            message=guard_message(
                message_id=71,
                text=None,
                left_chat_member=user,
                date=int((base.date + timedelta(seconds=1)).timestamp()),
            ),
        ),
        context,
    )
    await runtime.preprocess(
        Update(
            132,
            message=guard_message(
                message_id=72,
                text=None,
                new_chat_members=[user],
                date=int((base.date + timedelta(seconds=2)).timestamp()),
            ),
        ),
        context,
    )
    await kick(base.date + timedelta(seconds=3))
    await runtime.preprocess(
        Update(
            133,
            message=guard_message(
                message_id=73,
                text=None,
                left_chat_member=user,
                date=int((base.date + timedelta(seconds=3)).timestamp()),
            ),
        ),
        context,
    )

    async with engine.new_session() as session:
        rows = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == guard_group,
                    GuardTask.kind == "delete",
                )
            )
        ).all()
    message_ids = [row.data["message_id"] for row in rows]
    assert sorted(message_ids) == [70, 71, 72, 73]
    assert len(message_ids) == len(set(message_ids))


async def test_delayed_departure_does_not_clear_new_join_verification(
    guard_group, guard_bot, guard_message
):
    await store.save_policy(guard_group, {"verification_enabled": True})
    message = guard_message()
    context = SimpleNamespace(bot=guard_bot)
    new_join = message.date + timedelta(seconds=2)
    await runtime.member_joined(guard_bot, message.chat, message.from_user, new_join)
    old_departure = membership(
        message,
        guard_bot,
        restricted(message.from_user),
        {
            "status": "left",
            "user": message.from_user.to_dict(),
        },
    )
    await runtime.membership(old_departure, context)
    async with engine.new_session() as session:
        assert (await session.get(Pending, (guard_group, 2))).state == "pending"
    assert (await store.record(guard_group, "join_seen", "2"))["data"][
        "timestamp"
    ] == new_join.timestamp()


async def test_real_permission_edit_retires_restriction_and_allows_new_mute(
    guard_group, guard_bot, guard_message
):
    message = guard_message()
    result = await actions.execute(
        guard_bot,
        guard_group,
        ActionRequest(action="mute", user_id=2, request_id="mute"),
    )
    old_job = (await timers(guard_group))[0]
    old = restricted(message.from_user)
    guard_bot.members[2] = ChatMemberRestricted.de_json(
        old | {"can_send_photos": True}, guard_bot
    )
    await runtime.membership(
        membership(message, guard_bot, old, old | {"can_send_photos": True}, actor=1),
        SimpleNamespace(bot=guard_bot),
    )
    assert await store.record(guard_group, "restriction", "2") is None
    assert (await timers(guard_group))[0]["state"] == "cancelled"
    assert old_job["data"]["event_id"] == result["id"]
    guard_bot.restrict_chat_member.reset_mock()
    remute = await actions.execute(
        guard_bot,
        guard_group,
        ActionRequest(action="mute", user_id=2, request_id="mute-again"),
    )
    assert remute["status"] == "success"
    guard_bot.restrict_chat_member.assert_awaited_once()
    assert (await store.record(guard_group, "restriction", "2"))["data"][
        "event_id"
    ] == remute["id"]


@pytest.fixture
def timeout_job(guard_group, guard_bot, guard_message):
    async def create(kind):
        if kind == "verify":
            message = guard_message()
            await verification.start(
                guard_bot,
                guard_group,
                message.from_user,
                "Group",
                await store.policy(guard_group),
            )
        else:
            await actions.execute(
                guard_bot,
                guard_group,
                ActionRequest(
                    action="mute", user_id=2, duration=31536000, request_id="year-mute"
                ),
            )
        return (await timers(guard_group))[0]

    return create


@pytest.mark.parametrize("kind", ["verify", "unmute"])
async def test_repeated_recovery_reuses_original_durable_task(
    guard_group, guard_bot, timeout_job, kind
):
    original = await timeout_job(kind)
    for _ in range(4):
        await worker.Worker(guard_bot).recover()
    rows = await timers(guard_group)
    assert len(rows) == 1
    assert rows[0]["id"] == original["id"]
    assert rows[0]["due_at"] == original["due_at"]
    assert rows[0]["state"] == "pending"


@pytest.mark.parametrize("kind", ["verify", "unmute"])
@pytest.mark.parametrize("old_state", ["missing", "done", "uncertain"])
async def test_recovery_recreates_only_missing_pending_task(
    guard_group, guard_bot, timeout_job, kind, old_state
):
    original = await timeout_job(kind)
    if old_state == "missing":
        async with engine.new_session() as session:
            await session.execute(
                delete(GuardTask).where(GuardTask.id == original["id"])
            )
            await session.commit()
    else:
        await worker.set_state(original["id"], old_state)
    for _ in range(2):
        await worker.Worker(guard_bot).recover()
    rows = await timers(guard_group)
    pending = [row for row in rows if row["state"] == "pending"]
    assert len(pending) == 1 and pending[0]["id"] != original["id"]
    assert pending[0]["data"] == original["data"]
    assert pending[0]["due_at"] == original["due_at"]
    if old_state != "missing":
        assert (
            next(row for row in rows if row["id"] == original["id"])["state"]
            == old_state
        )


async def test_recovery_restores_unmute_task_for_applying_restriction(
    guard_group, guard_bot, timeout_job
):
    original = await timeout_job("unmute")
    restriction = await store.record(guard_group, "restriction", "2")
    await store.put_record(
        guard_group,
        "restriction",
        "2",
        restriction["data"] | {"state": "applying"},
    )
    async with engine.new_session() as session:
        await session.execute(delete(GuardTask).where(GuardTask.id == original["id"]))
        await session.commit()

    await worker.Worker(guard_bot).recover()
    await worker.Worker(guard_bot).recover()

    pending = [row for row in await timers(guard_group) if row["state"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["kind"] == "unmute"
    assert pending[0]["data"] == original["data"]
    assert pending[0]["due_at"] == original["due_at"]


@pytest.mark.parametrize("kind", ["verify", "unmute"])
async def test_recovery_collapses_old_duplicates_without_mixing_members_or_groups(
    guard_group, guard_bot, timeout_job, kind
):
    original = await timeout_job(kind)
    for _ in range(2):
        await store.task(guard_group, kind, original["due_at"], original["data"])
    others = [
        await store.task(guard_group + 1, kind, original["due_at"], original["data"]),
        await store.task(
            guard_group, kind, original["due_at"], original["data"] | {"user_id": 3}
        ),
        await store.task(
            guard_group,
            kind,
            original["due_at"],
            original["data"]
            | {"token" if kind == "verify" else "event_id": "old-generation"},
        ),
    ]
    for _ in range(2):
        await worker.Worker(guard_bot).recover()
    rows = [row for row in await timers(guard_group) if row["data"] == original["data"]]
    assert len(rows) == 3
    assert [row["id"] for row in rows if row["state"] == "pending"] == [original["id"]]
    assert sum(row["state"] == "cancelled" for row in rows) == 2
    async with engine.new_session() as session:
        for task_id in others:
            assert (await session.get(GuardTask, task_id)).state == "pending"
