from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone

from telegram import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

from services import group_guard
from utils import delete_messages, is_group_type

logger = logging.getLogger(__name__)

_VERIFICATION_CALLBACK_PREFIX = "guard:verify"
_DEFAULT_VERIFICATION_TEMPLATE = (
    "欢迎 {user} 加入 {chat}!\n"
    "请在 {timeout} 秒内点击下方按钮完成验证，否则将无法继续发言。"
)




def _create_background_task(
    context: ContextTypes.DEFAULT_TYPE,
    coroutine: Awaitable[object],
) -> asyncio.Task[object]:
    application = getattr(context, "application", None)
    if application and application.running:
        return application.create_task(coroutine)
    return asyncio.create_task(coroutine)

async def handle_new_member_verification(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    bot = context.bot

    if message is None or chat is None or bot is None:
        return
    if not is_group_type(chat.type):
        return

    new_members = message.new_chat_members or []
    if not new_members:
        return

    settings = await group_guard.get_guard_settings(chat.id)
    if not settings.verification_enabled:
        return

    for member in new_members:
        if member is None:
            continue
        if member.is_bot:
            continue
        if member.id == bot.id:
            continue

        display_name = member.full_name or member.username or "新成员"
        await _start_verification_flow(
            context,
            chat_id=chat.id,
            chat_title=chat.title or "本群",
            member_id=member.id,
            member_display=display_name,
            settings=settings,
        )


async def _start_verification_flow(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    chat_title: str,
    member_id: int,
    member_display: str,
    settings: group_guard.GuardSettings,
) -> None:
    bot = context.bot
    if bot is None:
        return

    timeout = max(15, settings.verification_timeout)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=timeout)
    token = group_guard.generate_token()

    await _restrict_member(bot, chat_id, member_id)

    text_template = settings.verification_message or _DEFAULT_VERIFICATION_TEMPLATE
    message_text = text_template.format(
        user=mention_html(member_id, member_display),
        chat=chat_title,
        timeout=timeout,
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ 点击完成验证",
                    callback_data=f"{_VERIFICATION_CALLBACK_PREFIX}:{token}",
                )
            ]
        ]
    )

    try:
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except TelegramError:
        logger.exception("Failed to send verification prompt for chat %s", chat_id)
        sent_message = None

    pending = await group_guard.upsert_pending_verification(
        group_id=chat_id,
        user_id=member_id,
        message_id=getattr(sent_message, "message_id", None),
        token=token,
        expires_at=expires_at,
    )

    if context.application is not None:
        _create_background_task(
            context,
            _schedule_verification_timeout(
                bot,
                pending,
                kick_on_timeout=settings.kick_on_timeout,
            ),
        )


async def _restrict_member(bot, chat_id: int, user_id: int) -> None:
    permissions = ChatPermissions(
        can_send_messages=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_audios=False,
    )
    try:
        logger.debug("Restricting user %s in chat %s", user_id, chat_id)
        await bot.restrict_chat_member(chat_id, user_id, permissions=permissions)
    except TelegramError as exc:
        logger.warning("Failed to restrict user %s in chat %s: %s", user_id, chat_id, exc)


async def _schedule_verification_timeout(
    bot,
    pending: group_guard.PendingVerification,
    *,
    kick_on_timeout: bool,
) -> None:
    remaining = (pending.expires_at - datetime.now(timezone.utc)).total_seconds()
    await asyncio.sleep(max(0, remaining))

    current = await group_guard.get_pending_verification(
        pending.group_id,
        pending.user_id,
    )
    if current is None or current.token != pending.token:
        return

    if not current.is_expired():
        return

    if current.message_id:
        try:
            await bot.delete_message(current.group_id, current.message_id)
        except TelegramError:
            logger.debug("Verification message already removed for %s", current)

    if kick_on_timeout:
        try:
            await bot.ban_chat_member(
                current.group_id,
                current.user_id,
                until_date=datetime.now(timezone.utc) + timedelta(seconds=60),
            )
            await bot.unban_chat_member(current.group_id, current.user_id)
        except TelegramError as exc:
            logger.warning(
                "Failed to remove unverified user %s in chat %s: %s",
                current.user_id,
                current.group_id,
                exc,
            )
    await group_guard.delete_pending_verification(current.group_id, current.user_id)

    try:
        member = await bot.get_chat_member(current.group_id, current.user_id)
        member_name = member.user.full_name if member and member.user else str(current.user_id)
    except TelegramError:
        member_name = str(current.user_id)

    try:
        await bot.send_message(
            current.group_id,
            text=f"{member_name} 未完成验证，已被移除。",
        )
    except TelegramError:
        logger.debug("Failed to send timeout notification for chat %s", current.group_id)


async def handle_group_keyword_filter(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    if not is_group_type(chat.type):
        return
    if message.from_user and message.from_user.is_bot:
        return

    text = message.text or message.caption
    if not text:
        return

    settings = await group_guard.get_guard_settings(chat.id)
    if not settings.keyword_filter_enabled:
        return

    matched_rule = await _find_matching_rule(chat.id, text)
    if matched_rule is None:
        return

    await _delete_message_safely(context, chat.id, message)
    await _notify_keyword_violation(context, chat.id, message, matched_rule)


async def _find_matching_rule(group_id: int, text: str) -> group_guard.KeywordRule | None:
    rules = await group_guard.list_keyword_rules(group_id)
    if not rules:
        return None

    for rule in rules:
        if rule.is_regex:
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(rule.pattern, flags)
            except re.error:
                logger.warning("Invalid regex rule %s ignored", rule.pattern)
                continue
            if pattern.search(text):
                return rule
        else:
            haystack = text if rule.case_sensitive else text.lower()
            needle = rule.pattern if rule.case_sensitive else rule.pattern.lower()
            if needle in haystack:
                return rule
    return None


async def _delete_message_safely(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: Message,
) -> None:
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except TelegramError as exc:
        logger.warning(
            "Failed to delete message %s in chat %s: %s",
            message.message_id,
            chat_id,
            exc,
        )


async def _notify_keyword_violation(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: Message,
    rule: group_guard.KeywordRule,
) -> None:
    user = message.from_user
    if user is None:
        return

    mention = mention_html(user.id, user.full_name or user.username or "成员")
    flags = []
    if rule.is_regex:
        flags.append("正则")
    if rule.case_sensitive:
        flags.append("区分大小写")
    flag_text = f" ({', '.join(flags)})" if flags else ""
    warning_text = (
        f"{mention} 触发了关键字规则#{rule.id}{flag_text}，消息已删除。"
    )

    try:
        warn_message = await context.bot.send_message(
            chat_id,
            text=warning_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.warning("Failed to send keyword warning in chat %s: %s", chat_id, exc)
        return

    if context.application is not None:
        _create_background_task(
            context,
            delete_messages(
                message_ids=[warn_message.message_id],
                chat_id=chat_id,
                context=context,
                delay=30,
            ),
        )
