"""Departures must retire old member state; restarts must reuse durable timers."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from telegram import ChatMemberRestricted, Update

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
