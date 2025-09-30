"""Message handler that stores Pixiv refresh tokens submitted via chat."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry, config_registry

from handlers.callback_handlers.conf_handlers.bot.panel import refresh_bot_config_panel

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "set_pixiv_token"


async def set_pixiv_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None or not message.text:
        return

    handler_key = await active_message_handler_registry.get(user.id)
    if not handler_key or not handler_key.startswith(_HANDLER_PREFIX):
        return

    _, _, metadata = handler_key.partition(":")
    if not metadata:
        logger.warning("Pixiv token handler metadata missing for user %s", user.id)
        await active_message_handler_registry.delete(user_id=user.id)
        return

    try:
        panel_message_id = int(metadata)
    except ValueError:
        logger.warning("Invalid Pixiv handler metadata '%s' for user %s", metadata, user.id)
        await active_message_handler_registry.delete(user_id=user.id)
        return

    submitted = message.text.strip()

    if submitted == "-":
        await config_registry.set_pixiv_token(None)
        await config_registry.set_pixiv_token_enabled(False)
        feedback = "已清除 Pixiv Refresh Token，并禁用 Pixiv 功能"
    else:
        await config_registry.set_pixiv_token(submitted)
        feedback = "已更新 Pixiv Refresh Token"

    await active_message_handler_registry.delete(user_id=user.id)

    await refresh_bot_config_panel(
        context,
        chat_id=message.chat_id,
        message_id=panel_message_id,
    )

    await context.bot.send_message(chat_id=message.chat_id, text=feedback)
