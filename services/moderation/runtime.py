import hashlib
import json

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy import update as sql_update
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop

from models import (
    ActiveMessageHandler,
    CommandHistory,
    Group,
    GroupChatHistory,
    GroupGuardKeywordRule,
    GroupGuardPendingVerification,
    GroupGuardSettings,
    GuardEvent,
    GuardRecord,
    GuardTask,
)
from registries import engine
from services.telegram_cache import get_cached_admin_ids, invalidate_chat_admins

from . import actions, ai, rules, store, verification


async def remember_message(group_id: int, message):
    version = rules.version(message)
    timestamp = (message.edit_date or message.date).timestamp()
    async with store.lock(group_id):
        previous = await store.record(group_id, "message", str(message.message_id))
        if previous and previous["data"].get("version") == version:
            if previous["data"].get("blocked"):
                raise ApplicationHandlerStop
            return None
        # Ignore older out-of-order edits.
        if previous and previous["data"].get("timestamp", 0) > timestamp:
            raise ApplicationHandlerStop
        await store.put_record(
            group_id,
            "message",
            str(message.message_id),
            {"version": version, "timestamp": timestamp, "blocked": False},
        )
    return version, timestamp


async def preprocess(update, context):
    message, chat = update.effective_message, update.effective_chat
    if not message or not chat or chat.type not in {"group", "supergroup"}:
        return
    if message.migrate_to_chat_id:
        await migrate(chat.id, message.migrate_to_chat_id)
        return
    if message.migrate_from_chat_id:
        await migrate(message.migrate_from_chat_id, chat.id)
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
    if not (
        settings.keyword_filter_enabled
        or settings.rules_enabled
        or settings.flood_enabled
        or ai.should_classify(message, settings)
    ):
        # Edits still invalidate reports created for an earlier content version.
        if message.edit_date:
            await remember_message(chat.id, message)
        return
    user_id = (
        message.from_user.id if message.from_user and not message.sender_chat else None
    )
    if user_id:
        if user_id == context.bot.id:
            return
        admin_ids = await get_cached_admin_ids(context, chat.id)
        if admin_ids is None or user_id in admin_ids:
            if message.edit_date:
                await remember_message(chat.id, message)
            return  # Cannot safely classify an unknown administrator as an ordinary member.
        exempt = await store.record(chat.id, "exempt", str(user_id))
        if exempt and exempt["enabled"]:
            if message.edit_date:
                await remember_message(chat.id, message)
            return
    incident = (
        f"album:{message.media_group_id}"
        if message.media_group_id
        else f"message:{message.message_id}"
    )
    remembered = await remember_message(chat.id, message)
    if remembered is None:
        return
    version, timestamp = remembered
    hit = await rules.evaluate(message, settings)
    if hit:
        await store.put_record(
            chat.id,
            "message",
            str(message.message_id),
            {"version": version, "timestamp": timestamp, "blocked": True},
        )
        try:
            await actions.punish(
                context.bot,
                chat.id,
                user_id,
                message.message_id,
                incident,
                hit["reason"],
                warn=hit["warn"],
                expected={"version": version},
            )
        except (ValueError, TelegramError) as exc:
            # A rejected/failed preflight must not let blocked content reach
            # later command, auto-reply or image handlers.
            await store.event(
                chat.id,
                "moderation",
                status="failed",
                user_id=user_id,
                message_id=message.message_id,
                reason=type(exc).__name__,
                data={"stage": "punishment", "version": version},
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
        try:
            handled = await verification.joined(bot, chat, user, lock_held=True)
        except (ValueError, TelegramError) as exc:
            status = "uncertain" if actions.is_uncertain_error(exc) else "failed"
            await store.event(
                chat.id,
                "join",
                status=status,
                user_id=user.id,
                reason=type(exc).__name__,
            )
            return
        if handled:
            await store.put_record(
                chat.id, "join_seen", str(user.id), {"timestamp": timestamp}
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
            .values(**store.verification_outcome("cancelled", "成员已离群，验证取消"))
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
                task.completed_at = store.now()
        await session.commit()


async def membership(update, context):
    change = update.chat_member or update.my_chat_member
    if not change:
        return
    if change.chat.type not in {"group", "supergroup"}:
        return
    # Telegram sends my_chat_member when the bot is added, before any group
    # message exists. Persist the chat immediately so the admin console can
    # show it without waiting for user activity.
    async with engine.new_session() as session:
        group = await session.get(Group, change.chat.id)
        if group is None:
            session.add(Group(id=change.chat.id, name=change.chat.title))
        elif change.chat.title and group.name != change.chat.title:
            group.name = change.chat.title
        await session.commit()
    await invalidate_chat_admins(change.chat.id)

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
        if change.old_chat_member.to_dict() != change.new_chat_member.to_dict():
            async with store.lock(change.chat.id), engine.new_session() as session:
                event_key = hashlib.sha256(
                    f"{update.update_id}:{change.to_json()}".encode()
                ).hexdigest()
                seen = await session.scalar(
                    select(GuardRecord).where(
                        GuardRecord.group_id == change.chat.id,
                        GuardRecord.kind == "membership_seen",
                        GuardRecord.key == event_key,
                    )
                )
                if seen:
                    return
                event_time = change.date.replace(tzinfo=None)
                current_member = None

                async def applies_to(started_at):
                    nonlocal current_member
                    if event_time < started_at.replace(microsecond=0):
                        return False
                    if event_time == started_at.replace(microsecond=0):
                        # Telegram dates have second precision. A same-second
                        # event may precede our mutation; validate its live state.
                        if current_member is None:
                            current_member = await context.bot.get_chat_member(
                                change.chat.id, user_id
                            )
                        return (
                            current_member.status == change.new_chat_member.status
                            and actions.permissions_snapshot(current_member)
                            == actions.permissions_snapshot(change.new_chat_member)
                        )
                    return True

                restriction = await session.scalar(
                    select(GuardRecord).where(
                        GuardRecord.group_id == change.chat.id,
                        GuardRecord.kind == "restriction",
                        GuardRecord.key == str(user_id),
                    )
                )
                if restriction and await applies_to(restriction.created_at):
                    event_id = restriction.data.get("event_id")
                    await session.delete(restriction)
                    tasks = (
                        await session.scalars(
                            select(GuardTask).where(
                                GuardTask.group_id == change.chat.id,
                                GuardTask.kind == "unmute",
                                GuardTask.state == "pending",
                            )
                        )
                    ).all()
                    for task in tasks:
                        if task.data.get("event_id") == event_id:
                            task.state = "cancelled"
                            task.result = "其他管理员已修改成员权限，原禁言任务取消"
                            task.completed_at = store.now()
                pending = await session.get(
                    GroupGuardPendingVerification, (change.chat.id, user_id)
                )
                if pending and pending.state in {
                    "pending", "preparing", "processing", "restricted", "uncertain"
                } and await applies_to(pending.created_at):
                    await session.execute(
                        sql_update(GroupGuardPendingVerification)
                        .where(GroupGuardPendingVerification.token == pending.token)
                        .values(
                            **store.verification_outcome(
                                "external", "其他管理员已修改成员权限，验证停止"
                            )
                        )
                    )
                session.add(GuardRecord(
                    id=store.uid(), group_id=change.chat.id, kind="membership_seen",
                    key=event_key, data={}, created_at=store.now(),
                ))
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
            key = rules.normalize(row["key"])
            if key and key in rules.normalize(message.text):
                if len(rules.window((chat.id, "reply", row["key"]), 10)) == 1:
                    await message.reply_text(row["data"]["text"])
                break


async def migrate(old_id, new_id):
    if old_id == new_id:
        return
    first_id, second_id = sorted((old_id, new_id))
    async with (
        store.task_lock(first_id).write(),
        store.task_lock(second_id).write(),
        store.lock(first_id),
        store.lock(second_id),
        engine.new_session() as session,
    ):
        migration_marker = await session.scalar(
            select(GuardRecord).where(
                GuardRecord.group_id == new_id,
                GuardRecord.kind == "migration",
                GuardRecord.key == str(old_id),
            )
        )
        old_group = await session.get(Group, old_id)
        if old_group and migration_marker is None:
            data = {
                c.name: getattr(old_group, c.name)
                for c in Group.__table__.columns
                if c.name != "id"
            }
            new_group = await session.get(Group, new_id)
            if new_group:
                for key, value in data.items():
                    setattr(new_group, key, value)
            else:
                session.add(Group(id=new_id, **data))
        source_settings = await session.get(GroupGuardSettings, old_id)
        if source_settings:
            existing = await session.get(GroupGuardSettings, new_id)
            if existing:
                await session.delete(existing)
                await session.flush()
        # Telegram may deliver updates for the upgraded group before its migration
        # service message. Keep target rows when a natural key collides. Read keys
        # in bounded batches so a large message history does not fill memory.
        async def discard_collisions(model, columns, *, require_non_null=()):
            cursor = None
            while True:
                stmt = select(*columns).where(model.group_id == old_id)
                for column in require_non_null:
                    stmt = stmt.where(column.is_not(None))
                if cursor is not None:
                    stmt = stmt.where(
                        columns[0] > cursor[0]
                        if len(columns) == 1
                        else tuple_(*columns) > cursor
                    )
                source_keys = (
                    await session.execute(stmt.order_by(*columns).limit(500))
                ).all()
                if not source_keys:
                    break
                values = [tuple(row) for row in source_keys]
                target_stmt = select(*columns).where(model.group_id == new_id)
                if len(columns) == 1:
                    target_stmt = target_stmt.where(
                        columns[0].in_([value[0] for value in values])
                    )
                else:
                    target_stmt = target_stmt.where(tuple_(*columns).in_(values))
                collisions = [
                    tuple(row)
                    for row in (await session.execute(target_stmt)).all()
                ]
                if collisions:
                    predicate = (
                        columns[0].in_([value[0] for value in collisions])
                        if len(columns) == 1
                        else tuple_(*columns).in_(collisions)
                    )
                    await session.execute(
                        delete(model).where(model.group_id == old_id, predicate)
                    )
                cursor = values[-1]

        await discard_collisions(
            GroupGuardPendingVerification,
            (GroupGuardPendingVerification.user_id,),
        )
        await discard_collisions(GuardRecord, (GuardRecord.kind, GuardRecord.key))
        await discard_collisions(
            GuardEvent,
            (GuardEvent.incident, GuardEvent.action),
            require_non_null=(GuardEvent.incident,),
        )
        await discard_collisions(
            GroupChatHistory,
            (GroupChatHistory.message_id, GroupChatHistory.user_id),
        )
        await discard_collisions(
            ActiveMessageHandler,
            (ActiveMessageHandler.user_id,),
        )
        await session.flush()
        for model in (
            GroupGuardSettings,
            GroupGuardKeywordRule,
            GroupGuardPendingVerification,
            GuardRecord,
            GuardEvent,
            GuardTask,
            GroupChatHistory,
            ActiveMessageHandler,
        ):
            await session.execute(
                sql_update(model)
                .where(model.group_id == old_id)
                .values(group_id=new_id)
            )
        await session.execute(
            sql_update(CommandHistory)
            .where(CommandHistory.chat_id == old_id)
            .values(chat_id=new_id)
        )
        if migration_marker is None:
            session.add(
                GuardRecord(
                    id=store.uid(),
                    group_id=new_id,
                    kind="migration",
                    key=str(old_id),
                    data={},
                    created_at=store.now(),
                )
            )
        if old_group:
            await session.delete(old_group)
        await session.commit()
    from services import group_guard

    await group_guard._invalidate_settings_cache(old_id)
    await group_guard._invalidate_settings_cache(new_id)
    await group_guard._invalidate_keyword_cache(old_id)
    await group_guard._invalidate_keyword_cache(new_id)
