from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import Update, ChatPermissions
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

from services import group_guard

logger = logging.getLogger(__name__)


async def guard_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    cmd: list[str],
) -> None:
    if not cmd:
        return

    action = cmd[0]
    if action == "verify" and len(cmd) >= 2:
        await _handle_verification_callback(update, context, token=cmd[1])
        return

    query = update.callback_query
    if query is not None:
        await query.answer()


async def _handle_verification_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    token: str,
) -> None:
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot

    if query is None or chat is None or user is None or bot is None:
        return

    pending = await group_guard.get_pending_verification_by_token(token)
    if pending is None:
        await query.answer("验证已失效，请联系管理员", show_alert=True)
        return

    if pending.group_id != chat.id:
        await query.answer("验证信息与当前群组不匹配", show_alert=True)
        return

    if pending.user_id != user.id:
        await query.answer("只能本人完成验证", show_alert=True)
        return

    if pending.is_expired(now=datetime.now(timezone.utc)):
        await group_guard.delete_pending_verification(pending.group_id, pending.user_id)
        await query.answer("验证已过期，请联系管理员", show_alert=True)
        return

    await _lift_restrictions(bot, chat.id, user.id)

    if pending.message_id:
        try:
            await bot.delete_message(chat.id, pending.message_id)
        except TelegramError:
            logger.debug("Verification message already deleted for user %s", user.id)

    await group_guard.delete_pending_verification(pending.group_id, pending.user_id)

    try:
        await query.answer("验证通过，欢迎加入！", show_alert=False)
    except TelegramError:
        logger.debug("Failed to answer verification callback for user %s", user.id)

    welcome_text = f"{mention_html(user.id, user.full_name or user.username or '成员')} 验证成功，欢迎加入！"
    try:
        await bot.send_message(
            chat.id,
            text=welcome_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.debug("Failed to send verification success message in chat %s: %s", chat.id, exc)


async def _lift_restrictions(bot, chat_id: int, user_id: int) -> None:
    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_photos=True,
        can_send_audios=True,
        can_send_videos=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
        can_pin_messages=False,
        can_change_info=False,
    )
    try:
        await bot.restrict_chat_member(chat_id, user_id, permissions=permissions)
    except TelegramError as exc:
        logger.warning(
            "Failed to lift restrictions for user %s in chat %s: %s",
            user_id,
            chat_id,
            exc,
        )
