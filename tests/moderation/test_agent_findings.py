"""Safety regressions reproduced by the independent code review."""

import asyncio
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from telegram import ChatMember, ChatMemberRestricted, Update, User
from telegram.error import BadRequest, RetryAfter, TimedOut

from models import GroupGuardPendingVerification as Pending
from models import GuardEvent, GuardTask
from registries import engine
from services.moderation import actions, ai, runtime, store, verification, worker
from services.moderation.schemas import ActionRequest, AIVerdict


@pytest.mark.parametrize("route", ["verification", "manual", "scheduler"])
@pytest.mark.parametrize("remaining,error", [
    (1, None), (20, None), (30, None), (59, None), (20, "rate_limit"), (20, "timeout"),
])
async def test_short_original_restriction_has_durable_final_release(
    guard_group, guard_bot, monkeypatch, route, remaining, error
):
    clock = store.now()
    monkeypatch.setattr(store, "now", lambda: clock)
    deadline = clock + timedelta(seconds=remaining + (60 if route == "scheduler" else 0))
    user = User(2, "Member", False)
    lookup = guard_bot.get_chat_member.side_effect

    async def member(group_id, user_id):
        if user_id == 2:
            return SimpleNamespace(
                status="restricted", user=user,
                until_date=deadline.replace(tzinfo=timezone.utc),
            )
        return await lookup(group_id, user_id)

    guard_bot.get_chat_member.side_effect = member
    failure = RetryAfter(10) if error == "rate_limit" else TimedOut() if error else None
    if route == "verification":
        await verification.start(guard_bot, guard_group, user, "Group", await store.policy(guard_group))
        async with engine.new_session() as session:
            token = (await session.get(Pending, (guard_group, 2))).token
        guard_bot.restrict_chat_member.side_effect = failure
        await verification.finish(guard_bot, guard_group, 2, token)
    else:
        await actions.execute(guard_bot, guard_group, ActionRequest(
            action="mute", user_id=2, duration=60, request_id="temporary-mute",
        ))
        guard_bot.restrict_chat_member.side_effect = failure
        if route == "manual":
            result = await actions.execute(guard_bot, guard_group, ActionRequest(
                action="unmute", user_id=2, request_id="restore-prior",
            ))
            assert result["status"] == (
                "failed" if error == "rate_limit" else "uncertain" if error else "success"
            )
        else:
            clock += timedelta(seconds=60)
            await worker.Worker(guard_bot).tick()
    call = guard_bot.restrict_chat_member.call_args
    assert call.kwargs["until_date"] is None
    assert call.args[2].can_send_messages is False
    record = await store.record(guard_group, "restriction", "2")
    assert record and record["data"]["deadline"] == deadline.isoformat()
    guard_bot.restrict_chat_member.side_effect = None
    restarted = worker.Worker(guard_bot)
    await restarted.recover()
    await restarted.tick()
    assert await store.record(guard_group, "restriction", "2")
    clock = deadline
    await restarted.tick()
    assert await store.record(guard_group, "restriction", "2") is None
    assert guard_bot.restrict_chat_member.call_args.args[2].can_send_messages is True


@pytest.mark.parametrize("pass_first", [False, True])
async def test_failed_verification_retry_survives_original_restriction_deadline(
    guard_group, guard_bot, monkeypatch, pass_first
):
    clock = store.now()
    monkeypatch.setattr(store, "now", lambda: clock)
    deadline = clock + timedelta(seconds=20)
    user = User(2, "Member", False)
    state = {
        "user": user.to_dict(), "status": "restricted", "is_member": True,
        "until_date": int(deadline.replace(tzinfo=timezone.utc).timestamp()),
        **{key: False for key in ChatMemberRestricted.__slots__ if key.startswith("can_")},
    }
    guard_bot.members[2] = ChatMember.de_json(state, guard_bot)

    async def restrict(group_id, user_id, permissions, **kwargs):
        until = kwargs.get("until_date")
        state.update(permissions.to_dict())
        state["until_date"] = int(until.timestamp()) if until else 0
        guard_bot.members[2] = ChatMember.de_json(state, guard_bot)
        return True

    guard_bot.restrict_chat_member.side_effect = restrict
    guard_bot.send_message.side_effect = BadRequest("prompt unavailable")
    settings = await store.policy(guard_group)
    assert not await verification.start(guard_bot, guard_group, user, "Group", settings)
    guard_bot.send_message.side_effect = None
    clock += timedelta(seconds=1)
    assert await verification.start(guard_bot, guard_group, user, "Group", settings)
    async with engine.new_session() as session:
        token = (await session.get(Pending, (guard_group, 2))).token
    if pass_first:
        await verification.finish(guard_bot, guard_group, 2, token)
    clock = deadline
    restarted = worker.Worker(guard_bot)
    await restarted.recover()
    await restarted.tick()
    if not pass_first:
        assert not guard_bot.members[2].can_send_messages
        async with engine.new_session() as session:
            assert (await session.get(Pending, (guard_group, 2))).state == "pending"
        await verification.finish(guard_bot, guard_group, 2, token)
    assert guard_bot.members[2].can_send_messages


@pytest.mark.parametrize("second_operation", ["config", "shutdown"])
async def test_bot_lifecycle_serializes_concurrent_operations(monkeypatch, second_operation):
    import bot as module

    entered, release = asyncio.Event(), asyncio.Event()

    async def initializing():
        entered.set()
        await release.wait()

    apps = []
    for index in range(2):
        app = MagicMock()
        app.bot = SimpleNamespace(id=999)
        app.running, app.updater = False, None
        app.initialize = AsyncMock(side_effect=initializing if index == 0 else None)
        app.shutdown = AsyncMock()
        apps.append(app)
    builder = MagicMock()
    builder.token.return_value = builder
    builder.read_timeout.return_value = builder
    builder.connect_timeout.return_value = builder
    builder.build.side_effect = apps
    workers = []

    class FakeWorker:
        def __init__(self, bot):
            self.running = False
            workers.append(self)

        async def start(self):
            assert not any(w.running for w in workers)
            self.running = True

        async def stop(self):
            self.running = False

    monkeypatch.setattr(module, "ApplicationBuilder", lambda: builder)
    monkeypatch.setattr(module.config_registry, "get_bot_tokens", AsyncMock(
        return_value=[SimpleNamespace(enable=True, token="123:test")]
    ))
    monkeypatch.setattr(worker, "Worker", FakeWorker)
    bot = module.TelegramBot()
    bot._register_commands = AsyncMock()
    bot._ensure_polling_mode = AsyncMock()
    bot._ensure_webhook_mode = AsyncMock()
    first = asyncio.create_task(bot.config())
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(getattr(bot, second_operation)())
    try:
        await asyncio.sleep(0)
        assert not second.done() and builder.build.call_count == 1
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 5)
        assert sum(w.running for w in workers) == (second_operation == "config")
        await bot.shutdown()
        assert not any(w.running for w in workers)
    finally:
        release.set()
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_catalogue_grades_do_not_exhaust_model_budget(
    guard_group, guard_bot, guard_ai_job, monkeypatch
):
    monkeypatch.setattr(ai, "known_image_grade", AsyncMock(side_effect=[
        {"sanity_level": 5, "r18g": False},
        {"sanity_level": 6, "r18g": False},
    ]))
    classifier = AsyncMock(return_value=(AIVerdict(category="spam", confidence=1, reason="spam"), {}))
    monkeypatch.setattr(ai, "classify", classifier)
    for message_id, expected in ((10, "allow"), (11, "punish")):
        job = await guard_ai_job(
            policy={"ai_daily_limit": 1, "ai_images": True, "ai_spam": False},
            message_id=message_id, text=None,
            photo=[{"file_id": "known", "file_unique_id": "known", "width": 1, "height": 1}],
        )
        assert await ai.process(guard_bot, job) == expected
    classifier.assert_not_awaited()
    job = await guard_ai_job(policy={"ai_daily_limit": 1}, message_id=12)
    assert await ai.process(guard_bot, job) == "punish"
    classifier.assert_awaited_once()
    # Even a genuinely exhausted provider budget cannot bypass known grades.
    monkeypatch.setattr(ai, "known_image_grade", AsyncMock(return_value={"sanity_level": 6, "r18g": False}))
    job = await guard_ai_job(
        policy={"ai_daily_limit": 1, "ai_images": True, "ai_spam": False},
        message_id=13, text=None,
        photo=[{"file_id": "known", "file_unique_id": "known", "width": 1, "height": 1}],
    )
    assert await ai.process(guard_bot, job) == "punish"
    async with engine.new_session() as session:
        events = (await session.scalars(select(GuardEvent).where(GuardEvent.action == "ai"))).all()
        assert len(events) == 1


@pytest.mark.parametrize("category,expected", [("image", "allow"), ("spam", "punish"), ("abuse", "punish")])
async def test_text_fallback_only_accepts_enabled_request_categories(
    guard_bot, guard_ai_job, monkeypatch, category, expected
):
    job = await guard_ai_job(
        policy={"ai_images": True, "ai_abuse": True}, text=None, caption="hello",
        photo=[{"file_id": "bad", "file_unique_id": "bad", "width": 1, "height": 1}],
    )
    monkeypatch.setattr(ai, "image_data", AsyncMock(side_effect=ValueError("bad image")))
    classifier = AsyncMock(return_value=(AIVerdict(
        category=category, confidence=1, reason="model", sanity_level=6, r18g=False,
    ), {}))
    monkeypatch.setattr(ai, "classify", classifier)
    assert await ai.process(guard_bot, job) == expected
    assert not classifier.call_args.args[1].ai_images
    assert classifier.call_args.args[3] is None
    if expected == "allow":
        guard_bot.delete_message.assert_not_awaited()


@pytest.mark.parametrize("new_state", ["mute", "verification"])
@pytest.mark.parametrize("delivery", ["duplicate", "delayed", "same_second"])
async def test_old_permission_events_cannot_retire_new_recovery_state(
    guard_group, guard_bot, guard_message, monkeypatch, new_state, delivery
):
    clock = store.now().replace(microsecond=0)
    monkeypatch.setattr(store, "now", lambda: clock)
    user = User(2, "Member", False)
    restricted = {"user": user.to_dict(), "status": "restricted", "is_member": True, "until_date": 0}
    # ChatMemberRestricted requires every permission field in Telegram payloads.
    from telegram import ChatMemberRestricted
    restricted.update({key: False for key in ChatMemberRestricted.__slots__ if key.startswith("can_")})
    event = Update.de_json({"update_id": 91, "chat_member": {
        "chat": guard_message().chat.to_dict(),
        "from": {"id": 1, "first_name": "Admin", "is_bot": False},
        "date": int(clock.replace(tzinfo=timezone.utc).timestamp()),
        "old_chat_member": restricted,
        "new_chat_member": {"status": "member", "user": user.to_dict()},
    }}, guard_bot)
    context = SimpleNamespace(bot=guard_bot)
    if delivery == "duplicate":
        await runtime.membership(event, context)
    if delivery != "same_second":
        clock += timedelta(seconds=5)
    if new_state == "mute":
        await actions.execute(guard_bot, guard_group, ActionRequest(
            action="mute", user_id=2, request_id="new-mute",
        ))
    else:
        await verification.start(guard_bot, guard_group, user, "Group", await store.policy(guard_group))
    current_member = ChatMember.de_json(restricted, guard_bot)
    guard_bot.get_chat_member.side_effect = AsyncMock(return_value=current_member)
    await runtime.membership(event, context)
    if new_state == "mute":
        assert await store.record(guard_group, "restriction", "2")
    else:
        async with engine.new_session() as session:
            assert (await session.get(Pending, (guard_group, 2))).state == "pending"
    async with engine.new_session() as session:
        assert any(task.state == "pending" for task in (await session.scalars(select(GuardTask))).all())

async def test_failed_verification_prompt_preserves_existing_mute(guard_group, guard_bot):
    user = User(2, "Member", False)
    state = {
        "user": user.to_dict(), "status": "restricted", "is_member": True,
        "until_date": 0,
        **{key: False for key in ChatMemberRestricted.__slots__ if key.startswith("can_")},
    }

    async def restrict(group_id, user_id, permissions, **kwargs):
        until = kwargs.get("until_date")
        state.update(permissions.to_dict())
        state["until_date"] = int(until.timestamp()) if until else 0
        guard_bot.members[2] = ChatMember.de_json(state, guard_bot)
        return True

    guard_bot.restrict_chat_member.side_effect = restrict
    result = await actions.execute(guard_bot, guard_group, ActionRequest(
        action="mute", user_id=2, duration=3600, request_id="prior-mute",
    ))
    assert result["status"] == "success"
    before = await store.record(guard_group, "restriction", "2")
    guard_bot.send_message.side_effect = BadRequest("prompt unavailable")
    assert not await verification.start(
        guard_bot, guard_group, user, "Group", await store.policy(guard_group)
    )
    assert not guard_bot.members[2].can_send_messages
    after = await store.record(guard_group, "restriction", "2")
    assert after["data"] == before["data"]
