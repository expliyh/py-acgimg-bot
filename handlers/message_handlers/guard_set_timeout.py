"""Message handler for updating guard verification timeout via chat."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, filters

from handlers.callback_handlers.conf_handlers.group_conf_handlers.panel import (
    refresh_group_config_panel,
)
from registries import active_message_handler_registry
from services import group_guard
from handlers.registry import message_handler

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "guard_set_timeout"
_MIN_TIMEOUT = 15
_MAX_TIMEOUT = 3600
_CANCEL_TOKENS = {"-", "取消", "cancel"}


@message_handler(filters=filters.TEXT & ~filters.COMMAND)
async def guard_set_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    logger.info("Received guard timeout message for user %s", user.id)

    if message is None or user is None or chat is None or not message.text:
        return

    handler_key = await active_message_handler_registry.get(user.id, group_id=chat.id)
    if not handler_key or not handler_key.startswith(_HANDLER_PREFIX):
        return


    _, _, metadata = handler_key.partition(":")
    try:
        panel_message_id = int(metadata)
    except (TypeError, ValueError):
        logger.warning("Guard timeout handler metadata missing for user %s", user.id)
        await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)
        return

    submitted = message.text.strip()

    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=message.id)
    except TelegramError:
        logger.debug("Failed to delete guard timeout message for user %s", user.id)

    if submitted.lower() in _CANCEL_TOKENS:
        await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)
        await context.bot.send_message(chat_id=chat.id, text="已取消设置验证超时")
        return

    try:
        timeout = int(submitted)
    except ValueError:
        await context.bot.send_message(chat_id=chat.id, text="请输入有效的秒数")
        return

    if timeout < _MIN_TIMEOUT or timeout > _MAX_TIMEOUT:
        await context.bot.send_message(
            chat_id=chat.id,
            text=f"超时必须在 {_MIN_TIMEOUT}-{_MAX_TIMEOUT} 秒之间",
        )
        return

    updated = await group_guard.set_verification_timeout(chat.id, timeout)
    await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)

    await refresh_group_config_panel(
        context,
        chat_id=chat.id,
        message_id=panel_message_id,
        group_id=chat.id,
    )

    await context.bot.send_message(
        chat_id=chat.id,
        text=f"验证超时已设置为 {updated.verification_timeout} 秒",
    )
