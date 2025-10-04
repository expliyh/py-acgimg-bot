"""Message handler for updating guard verification message via chat."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from handlers.callback_handlers.conf_handlers.group_conf_handlers.panel import (
    refresh_group_config_panel,
)
from registries import active_message_handler_registry
from services import group_guard
from handlers.registry import message_handler

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "guard_set_message"
_CANCEL_TOKENS = {"-", "默认", "default", "取消", "cancel"}
_MAX_LENGTH = 400


@message_handler
async def guard_set_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if message is None or user is None or chat is None or not message.text:
        return

    handler_key = await active_message_handler_registry.get(user.id, group_id=chat.id)
    if not handler_key or not handler_key.startswith(_HANDLER_PREFIX):
        return

    _, _, metadata = handler_key.partition(":")
    try:
        panel_message_id = int(metadata)
    except (TypeError, ValueError):
        logger.warning("Guard message handler metadata missing for user %s", user.id)
        await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)
        return

    submitted = message.text.strip()

    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=message.id)
    except TelegramError:
        logger.debug("Failed to delete guard message update for user %s", user.id)

    if submitted.lower() in _CANCEL_TOKENS:
        updated = await group_guard.set_verification_message(chat.id, None)
        await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)
        await refresh_group_config_panel(
            context,
            chat_id=chat.id,
            message_id=panel_message_id,
            group_id=chat.id,
        )
        await context.bot.send_message(chat_id=chat.id, text="已恢复默认验证提示")
        return

    if len(submitted) > _MAX_LENGTH:
        await context.bot.send_message(
            chat_id=chat.id,
            text=f"验证提示过长，请控制在 {_MAX_LENGTH} 字符以内",
        )
        return

    updated = await group_guard.set_verification_message(chat.id, submitted)
    await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)

    await refresh_group_config_panel(
        context,
        chat_id=chat.id,
        message_id=panel_message_id,
        group_id=chat.id,
    )

    preview = updated.verification_message or "默认提示"
    await context.bot.send_message(chat_id=chat.id, text=f"验证提示已更新为: {preview}")
