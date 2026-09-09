import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter, TelegramError

from models import GroupGuardPendingVerification as Pending
from registries import engine

from . import actions, reviews, rules, store


def greeting(template, user, chat, timeout=60):
    # No .format(): administrator templates and chat names are literal text.
    return (
        template.replace("{user}", user)
        .replace("{chat}", chat)
        .replace("{timeout}", str(timeout))
    )


@asynccontextmanager
async def _verification_lock(group_id, lock_held):
    if lock_held:
        yield
    else:
        async with store.lock(group_id):
            yield


async def start(
    bot, group_id, member, title, settings, *, force=False, lock_held=False
):
    if member.is_bot or await actions.is_admin(bot, group_id, member.id):
        return True
    async with _verification_lock(group_id, lock_held):
        async with engine.new_session() as session:
            previous = await session.get(Pending, (group_id, member.id))
            if previous and previous.state in {
                "pending",
                "preparing",
                "processing",
                "restricted",
                "uncertain",
            }:
                return True
        await actions.require_right(bot, group_id, "can_restrict_members")
        snapshot = actions.permissions_snapshot(
            await bot.get_chat_member(group_id, member.id)
        )
        rollback_snapshot = snapshot
        prior_restriction = await store.record(group_id, "restriction", str(member.id))
        if prior_restriction:
            # An earlier timed restriction may currently be represented by a
            # permanent Telegram mask. Keep its true recovery chain, not that mask.
            snapshot = prior_restriction["data"]["original"]
        token = secrets.token_hex(12)
        timeout = settings.verification_timeout
        deadline = store.now() + timedelta(seconds=timeout)
        answer = None
        text = greeting(
            settings.verification_message
            or "欢迎 {user} 加入 {chat}！请在 {timeout} 秒内验证。",
            member.full_name,
            title,
            timeout,
        )
        if settings.verification_mode == "math" or force:
            a, b = secrets.randbelow(9) + 1, secrets.randbelow(9) + 1
            answer = str(a + b)
            choices = [a + b, a + b + 1, max(0, a + b - 1)]
            secrets.SystemRandom().shuffle(choices)
            text += f"\n{a} + {b} = ?"
            keyboard = [
                [
                    InlineKeyboardButton(
                        str(choice), callback_data=f"guard:verify:{token}:{choice}"
                    )
                    for choice in choices
                ]
            ]
        else:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "点击验证", callback_data=f"guard:verify:{token}"
                    )
                ]
            ]
        async with engine.new_session() as session:
            row = await session.get(Pending, (group_id, member.id))
            if row is None:
                row = Pending(group_id=group_id, user_id=member.id)
                session.add(row)
            row.token, row.expires_at, row.state = token, deadline, "preparing"
            row.original_permissions, row.answer, row.result = snapshot, answer, None
            row.message_id = None
            row.completed_at = None
            row.created_at = store.now()
            await session.commit()
        await store.task(
            group_id, "verify", deadline, {"user_id": member.id, "token": token}
        )
        try:
            await bot.restrict_chat_member(
                group_id,
                member.id,
                ChatPermissions.no_permissions(),
                use_independent_chat_permissions=True,
            )
            sent = await bot.send_message(
                group_id, text[:4000], reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except TelegramError as exc:
            # If the prompt could not be delivered, undo only our verification restriction.
            result = type(exc).__name__
            try:
                await actions.restore_permissions(
                    bot, group_id, member.id, rollback_snapshot, verification_token=token
                )
                state = "failed"
            except TelegramError:
                state, result = "uncertain", result + "; restoration failed"
            async with engine.new_session() as session:
                await session.execute(
                    update(Pending)
                    .where(Pending.token == token)
                    .values(**store.verification_outcome(state, result))
                )
                await session.commit()
            await store.event(
                group_id, "verification", status=state, user_id=member.id, reason=result
            )
            # A successfully restored member can safely retry setup on a duplicate
            # Telegram join update. An uncertain restoration must not be repeated.
            return state == "uncertain"
        async with engine.new_session() as session:
            await session.execute(
                update(Pending)
                .where(Pending.token == token)
                .values(message_id=sent.message_id, state="pending")
            )
            await session.commit()
        return True


async def finish(bot, group_id, user_id, token, *, answer=None, expired=False):
    async with store.lock(group_id):
        async with engine.new_session() as session:
            row = await session.get(Pending, (group_id, user_id))
            if not row or row.token != token or row.state != "pending":
                return "验证已失效或已处理"
            if expired != (row.expires_at <= store.now()):
                return "验证已过期" if not expired else "验证尚未到期"
            if not expired and row.answer and answer != row.answer:
                return "答案错误，请重试"
            values = store.dump(row)
            result = await session.execute(
                update(Pending)
                .where(Pending.token == token, Pending.state == "pending")
                .values(state="processing")
            )
            await session.commit()
            if not result.rowcount:
                return "正在处理"
        settings = await store.policy(group_id)
        status, text = "passed", "验证通过"
        try:
            if await actions.is_admin(bot, group_id, user_id):
                text = "成员已成为管理员，验证结束"
            elif expired:
                if settings.kick_on_timeout:
                    await bot.ban_chat_member(
                        group_id,
                        user_id,
                        until_date=datetime.now(timezone.utc) + timedelta(minutes=1),
                    )
                    await bot.unban_chat_member(group_id, user_id, only_if_banned=True)
                    status, text = "removed", "验证超时，已移出群组"
                else:
                    # A later moderation mute owns its own deadline and snapshot.
                    # Its expiration restores the verification restriction; the
                    # pending verification retains the earlier recovery snapshot.
                    if not await store.record(group_id, "restriction", str(user_id)):
                        await store.put_record(
                            group_id,
                            "restriction",
                            str(user_id),
                            {
                                "original": values["original_permissions"] or {},
                                "state": "active",
                                "event_id": token,
                            },
                        )
                    status, text = "restricted", "验证超时，保持限制发言"
            else:
                # A later moderation mute must survive passing verification.
                restriction = await store.record(group_id, "restriction", str(user_id))
                if restriction:
                    await store.put_record(
                        group_id,
                        "restriction",
                        str(user_id),
                        restriction["data"]
                        | {"original": values["original_permissions"] or {}},
                    )
                else:
                    await actions.restore_permissions(
                        bot, group_id, user_id, values["original_permissions"] or {},
                        verification_token=token
                    )
        except (TelegramError, ValueError) as exc:
            status = "uncertain" if actions.is_uncertain_error(exc) else "failed"
            text = (
                f"操作未完成，请联系管理员（{type(exc).__name__}）"
                if status == "uncertain"
                else f"操作失败（{type(exc).__name__}）"
            )
        async with engine.new_session() as session:
            await session.execute(
                update(Pending)
                .where(Pending.token == token)
                .values(**store.verification_outcome(status, text))
            )
            await session.commit()
        await store.event(
            group_id,
            "verification",
            user_id=user_id,
            status=status,
            reason=text,
            incident=token,
        )
        if values["message_id"] and status != "uncertain":
            await store.task(
                group_id, "delete", store.now(), {"message_id": values["message_id"]}
            )
        if status == "passed" and settings.welcome_enabled:
            member = await bot.get_chat_member(group_id, user_id)
            chat = await bot.get_chat(group_id)
            await bot.send_message(
                group_id,
                greeting(
                    settings.welcome_text,
                    member.user.full_name,
                    chat.title or str(group_id),
                ),
            )
        return text


async def callback(update, context, parts):
    query = update.callback_query
    if (
        not query
        or not update.effective_chat
        or not update.effective_user
        or len(parts) < 2
    ):
        return
    token = parts[1]
    async with engine.new_session() as session:
        row = await session.scalar(select(Pending).where(Pending.token == token))
        if (
            not row
            or row.group_id != update.effective_chat.id
            or row.user_id != update.effective_user.id
        ):
            await query.answer("验证信息不匹配，只能本人验证", show_alert=True)
            return
    if len(rules.window((row.group_id, row.user_id, "verify-attempt"), 60)) > 5:
        await query.answer("验证尝试过于频繁，请联系管理员", show_alert=True)
        return
    await query.answer()
    result = await finish(
        context.bot,
        row.group_id,
        row.user_id,
        token,
        answer=parts[2] if len(parts) > 2 else None,
    )
    sent = await context.bot.send_message(row.group_id, result)
    await store.task(
        row.group_id,
        "delete",
        store.now() + timedelta(seconds=30),
        {"message_id": sent.message_id},
    )


async def joined(bot, chat, member, *, lock_held=False):
    settings = await store.policy(chat.id)
    if member.is_bot:
        return True
    raid = False
    if settings.raid_enabled:
        count = rules.window((chat.id, "joins"), settings.raid_window)
        if len(count) >= settings.raid_limit:
            await store.put_record(
                chat.id,
                "raid",
                "active",
                {
                    "until": (
                        store.now() + timedelta(seconds=settings.raid_duration)
                    ).isoformat()
                },
            )
        state = await store.record(chat.id, "raid", "active")
        raid = bool(state and state["data"]["until"] > store.now().isoformat())
    if settings.verification_enabled or raid:
        return await start(
            bot,
            chat.id,
            member,
            chat.title or str(chat.id),
            settings,
            force=raid,
            lock_held=lock_held,
        )
    elif settings.welcome_enabled:
        await bot.send_message(
            chat.id,
            greeting(
                settings.welcome_text, member.full_name, chat.title or str(chat.id)
            ),
        )
    return True


async def join_request(update, context):
    request = update.chat_join_request
    group_id = request.chat.id
    settings = await store.policy(group_id)
    if not settings.join_requests_enabled:
        return
    receipt, fresh = await store.event(
        group_id,
        "join_request",
        user_id=request.from_user.id,
        incident=f"request:{request.from_user.id}:{int(request.date.timestamp())}",
        status="running",
    )
    if not fresh:
        return
    settings = await store.policy(group_id)
    if (
        settings.raid_enabled
        and len(rules.window((group_id, "join-requests"), settings.raid_window))
        >= settings.raid_limit
    ):
        await store.put_record(
            group_id,
            "raid",
            "active",
            {
                "until": (
                    store.now() + timedelta(seconds=settings.raid_duration)
                ).isoformat()
            },
        )
    raid = await store.record(group_id, "raid", "active")

    async def create_review(result=None):
        await reviews.create(
            group_id,
            f"join:{request.from_user.id}:{int(request.date.timestamp())}",
            {
                "kind": "join",
                "user_id": request.from_user.id,
                "reason": f"入群申请：{request.from_user.full_name}",
            },
            context.bot,
        )
        await store.finish_event(
            receipt["id"], "success", {"review": True} | (result or {})
        )

    if settings.join_auto_approve and not (
        raid and raid["data"]["until"] > store.now().isoformat()
    ):
        try:
            await actions.require_right(context.bot, group_id, "can_invite_users")
        except (ValueError, TelegramError) as exc:
            await create_review(
                {
                    "auto_approve": "unavailable",
                    "error": str(exc)
                    if isinstance(exc, ValueError)
                    else type(exc).__name__,
                }
            )
            return
        try:
            await context.bot.approve_chat_join_request(group_id, request.from_user.id)
            await store.finish_event(receipt["id"], "success", {"approved": True})
        except TelegramError as exc:
            if isinstance(exc, RetryAfter):
                # Approval was rejected, so an administrator may safely retry
                # from the durable review even if its notification is rate limited.
                await create_review(
                    {"auto_approve": "rate_limited", "error": "RetryAfter"}
                )
                return
            await store.finish_event(
                receipt["id"],
                "uncertain" if actions.is_uncertain_error(exc) else "failed",
                {"error": type(exc).__name__},
            )
    else:
        await create_review()
