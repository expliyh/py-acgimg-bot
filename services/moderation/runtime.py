import json

from sqlalchemy import delete, func, select
from sqlalchemy import update as sql_update
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop

from models import (
    Group,
    GroupGuardKeywordRule,
    GroupGuardPendingVerification,
    GroupGuardSettings,
    GuardEvent,
    GuardRecord,
    GuardTask,
)
from registries import engine

from . import actions, ai, rules, store, verification


async def preprocess(update, context):
    message, chat = update.effective_message, update.effective_chat
    if not message or not chat or chat.type not in {"group", "supergroup"}:
        return
    if message.migrate_to_chat_id:
        await migrate(chat.id, message.migrate_to_chat_id)
        return
    settings = await store.policy(chat.id)
    for member in message.new_chat_members or []:
        await member_joined(context.bot, chat, member, message.date)
    if message.left_chat_member:
        await member_left(chat.id, message.left_chat_member.id, message.date)
    if message.left_chat_member and settings.goodbye_enabled:
        await context.bot.send_message(
            chat.id,
            verification.greeting(
                settings.goodbye_text,
                message.left_chat_member.full_name,
                chat.title or str(chat.id),
            ),
        )
    if message.new_chat_members or message.left_chat_member:
        if settings.clean_service_messages:
            await store.task(
                chat.id, "delete", store.now(), {"message_id": message.message_id}
            )
        return
    if not (message.text or message.caption or message.effective_attachment):
        return
    if message.sender_chat and message.sender_chat.id == chat.id:
        return
    user_id = (
        message.from_user.id if message.from_user and not message.sender_chat else None
    )
    if user_id:
        try:
            if user_id == context.bot.id or await actions.is_admin(
                context.bot, chat.id, user_id
            ):
                return
        except TelegramError:
            return  # Cannot safely classify an unknown administrator as an ordinary member.
        exempt = await store.record(chat.id, "exempt", str(user_id))
        if exempt and exempt["enabled"]:
            return
    incident = (
        f"album:{message.media_group_id}"
        if message.media_group_id
        else f"message:{message.message_id}"
    )
    version = rules.version(message)
    async with store.lock(chat.id):
        previous = await store.record(chat.id, "message", str(message.message_id))
        if previous and previous["data"].get("version") == version:
            if previous["data"].get("blocked"):
                raise ApplicationHandlerStop
            return
        # Ignore older out-of-order edits.
        timestamp = (message.edit_date or message.date).timestamp()
        if previous and previous["data"].get("timestamp", 0) > timestamp:
            raise ApplicationHandlerStop
        await store.put_record(
            chat.id,
            "message",
            str(message.message_id),
            {"version": version, "timestamp": timestamp, "blocked": False},
        )
    hit = await rules.evaluate(message, settings)
    if hit:
        await store.put_record(
            chat.id,
            "message",
            str(message.message_id),
            {"version": version, "timestamp": timestamp, "blocked": True},
        )
        await actions.punish(
            context.bot,
            chat.id,
            user_id,
            message.message_id,
            incident,
            hit["reason"],
            warn=hit["warn"],
        )
        from services.message_logging import log_message_update

        await log_message_update(update, context)
        raise ApplicationHandlerStop
    if ai.should_classify(message, settings):
        config = await store.ai_config()
        if config.base_url:
            async with engine.new_session() as session:
                pending = await session.scalar(
                    select(func.count())
                    .select_from(GuardTask)
                    .where(
                        GuardTask.group_id == chat.id,
                        GuardTask.kind == "ai",
                        GuardTask.state == "pending",
                    )
                )
            if pending < 100:
                await store.task(
                    chat.id,
                    "ai",
                    store.now(),
                    {
                        "message": json.loads(message.to_json()),
                        "version": version,
                        "incident": incident,
                        "policy": settings.model_dump(),
                    },
                )


async def member_joined(bot, chat, user, date):
    # Service messages and chat_member updates describe the same transition.
    async with store.lock(chat.id):
        old = await store.record(chat.id, "join_seen", str(user.id))
        timestamp = date.timestamp()
        if old and abs(old["data"]["timestamp"] - timestamp) < 10:
            return
        await store.put_record(
            chat.id, "join_seen", str(user.id), {"timestamp": timestamp}
        )
    try:
        await verification.joined(bot, chat, user)
    except (ValueError, TelegramError) as exc:
        await store.event(
            chat.id, "join", status="failed", user_id=user.id, reason=type(exc).__name__
        )


async def member_left(group_id, user_id, date):
    """Retire local state without changing Telegram bans or member permissions."""
    async with store.lock(group_id), engine.new_session() as session:
        joined = await session.scalar(
            select(GuardRecord).where(
                GuardRecord.group_id == group_id,
                GuardRecord.kind == "join_seen",
                GuardRecord.key == str(user_id),
            )
        )
        if joined and joined.data["timestamp"] > date.timestamp():
            return  # A delayed departure must not invalidate a newer join.
        await session.execute(
            delete(GuardRecord).where(
                GuardRecord.group_id == group_id,
                GuardRecord.kind.in_(["restriction", "join_seen"]),
                GuardRecord.key == str(user_id),
            )
        )
        await session.execute(
            sql_update(GroupGuardPendingVerification)
            .where(
                GroupGuardPendingVerification.group_id == group_id,
                GroupGuardPendingVerification.user_id == user_id,
                GroupGuardPendingVerification.state.in_(
                    [
                        "pending",
                        "preparing",
                        "processing",
                        "restricted",
                        "uncertain",
                        "external",
                    ]
                ),
            )
            .values(state="cancelled", result="成员已离群，验证取消")
        )
        tasks = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == group_id,
                    GuardTask.kind.in_(["verify", "unmute"]),
                    GuardTask.state == "pending",
                )
            )
        ).all()
        for task in tasks:
            if task.data.get("user_id") == user_id:
                task.state, task.result = "cancelled", "成员已离群，到期任务取消"
        await session.commit()


async def membership(update, context):
    change = update.chat_member or update.my_chat_member
    if not change:
        return
    if change.chat.type not in {"group", "supergroup"}:
        return

    def present(member):
        return (
            member.status in {"member", "administrator", "creator"}
            or member.status == "restricted"
            and member.is_member
        )

    was_present = present(change.old_chat_member)
    is_present = present(change.new_chat_member)
    if not was_present and is_present:
        await member_joined(
            context.bot, change.chat, change.new_chat_member.user, change.date
        )
    elif was_present and not is_present:
        await member_left(change.chat.id, change.new_chat_member.user.id, change.date)
    # Only a permission edit for a current member can invalidate our restriction.
    elif was_present and is_present and change.from_user.id != context.bot.id:
        user_id = change.new_chat_member.user.id
        restriction = await store.record(change.chat.id, "restriction", str(user_id))
        if (
            restriction
            and change.old_chat_member.to_dict() != change.new_chat_member.to_dict()
        ):
            await store.put_record(
                change.chat.id,
                "restriction",
                str(user_id),
                restriction["data"] | {"state": "external"},
            )
        if change.old_chat_member.to_dict() != change.new_chat_member.to_dict():
            async with engine.new_session() as session:
                await session.execute(
                    sql_update(GroupGuardPendingVerification)
                    .where(
                        GroupGuardPendingVerification.group_id == change.chat.id,
                        GroupGuardPendingVerification.user_id == user_id,
                        GroupGuardPendingVerification.state == "pending",
                    )
                    .values(
                        state="external", result="其他管理员已修改成员权限，验证停止"
                    )
                )
                await session.commit()
    await store.event(
        change.chat.id,
        "membership",
        user_id=change.new_chat_member.user.id,
        data={
            "old": change.old_chat_member.status,
            "new": change.new_chat_member.status,
        },
    )


async def operations(update, context):
    message, chat = update.effective_message, update.effective_chat
    if (
        not message
        or not chat
        or chat.type not in {"group", "supergroup"}
        or message.edit_date
        or not message.text
        or message.text.startswith("/")
    ):
        return
    if message.from_user and message.from_user.is_bot:
        return
    settings = await store.policy(chat.id)
    if settings.replies_enabled:
        for row in await store.records(chat.id, "reply", enabled=True):
            if rules.normalize(row["key"]) in rules.normalize(message.text):
                if len(rules.window((chat.id, "reply", row["key"]), 10)) == 1:
                    await message.reply_text(row["data"]["text"])
                break


async def migrate(old_id, new_id):
    async with store.lock(old_id), engine.new_session() as session:
        old_group = await session.get(Group, old_id)
        if old_group and not await session.get(Group, new_id):
            data = {
                c.name: getattr(old_group, c.name)
                for c in Group.__table__.columns
                if c.name != "id"
            }
            session.add(Group(id=new_id, **data))
        existing = await session.get(GroupGuardSettings, new_id)
        if existing:
            await session.delete(existing)
            await session.flush()
        for model in (
            GroupGuardSettings,
            GroupGuardKeywordRule,
            GroupGuardPendingVerification,
            GuardRecord,
            GuardEvent,
            GuardTask,
        ):
            await session.execute(
                sql_update(model)
                .where(model.group_id == old_id)
                .values(group_id=new_id)
            )
        await session.commit()
    from services import group_guard

    await group_guard._invalidate_settings_cache(old_id)
    await group_guard._invalidate_settings_cache(new_id)
