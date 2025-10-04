"""Message handler for updating Redis cache connection via chat."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from handlers.callback_handlers.conf_handlers.bot.panel import refresh_bot_config_panel
from registries import active_message_handler_registry, config_registry
from services.telegram_cache import telegram_cache_manager
from handlers.registry import message_handler

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "set_cache_redis"


@message_handler
async def set_cache_redis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        logger.warning("Cache redis handler metadata missing for user %s", user.id)
        await active_message_handler_registry.delete(user_id=user.id)
        return

    submitted = message.text.strip()
    normalized = submitted if submitted != "-" else ""

    try:
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.id)
    except TelegramError:
        logger.debug("Failed to delete redis command message for user %s", user.id)

    await config_registry.set_telegram_cache_redis_url(normalized or None)
    await telegram_cache_manager.reset()
    await active_message_handler_registry.delete(user_id=user.id)

    await refresh_bot_config_panel(
        context,
        chat_id=message.chat_id,
        message_id=panel_message_id,
    )

    if normalized:
        feedback = "已更新 Redis 地址"
    else:
        feedback = "已清除 Redis 地址"

    await context.bot.send_message(chat_id=message.chat_id, text=feedback)
