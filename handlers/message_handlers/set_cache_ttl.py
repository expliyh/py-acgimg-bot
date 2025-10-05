"""Message handler for updating Telegram cache TTL via chat."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, filters

from handlers.callback_handlers.conf_handlers.bot.panel import refresh_bot_config_panel
from registries import active_message_handler_registry, config_registry
from services.telegram_cache import telegram_cache_manager
from handlers.registry import message_handler

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "set_cache_ttl"
_MIN_TTL = 30


@message_handler(filters=filters.TEXT & ~filters.COMMAND)
async def set_cache_ttl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None or not message.text:
        return

    handler_key = await active_message_handler_registry.get(user.id)
    if not handler_key or not handler_key.startswith(_HANDLER_PREFIX):
        return

    _, _, metadata = handler_key.partition(":")
    try:
        panel_message_id = int(metadata)
    except (TypeError, ValueError):
        logger.warning("Cache TTL handler metadata missing for user %s", user.id)
        await active_message_handler_registry.delete(user_id=user.id)
        return

    submitted = message.text.strip()

    try:
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.id)
    except TelegramError:
        logger.debug("Failed to delete TTL command message for user %s", user.id)

    try:
        ttl_seconds = int(submitted)
    except ValueError:
        await context.bot.send_message(chat_id=message.chat_id, text="请输入有效的数字")
        return

    if ttl_seconds < _MIN_TTL:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text=f"TTL 必须大于等于 {_MIN_TTL} 秒",
        )
        return

    await config_registry.set_telegram_cache_ttl(ttl_seconds)
    await telegram_cache_manager.reset()
    await active_message_handler_registry.delete(user_id=user.id)

    await refresh_bot_config_panel(
        context,
        chat_id=message.chat_id,
        message_id=panel_message_id,
    )

    await context.bot.send_message(
        chat_id=message.chat_id,
        text=f"缓存 TTL 已更新为 {ttl_seconds} 秒",
    )
