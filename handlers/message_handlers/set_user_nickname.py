"""Message handler that applies nickname updates initiated from the config panel."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry, user_registry

from handlers.callback_handlers.conf_handlers.user_conf_handlers.panel import (
    refresh_user_config_panel,
)

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "set_user_nickname"


async def set_user_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None or not message.text:
        return

    handler_key = await active_message_handler_registry.get(user.id)
    if not handler_key or not handler_key.startswith(_HANDLER_PREFIX):
        return

    _, _, metadata = handler_key.partition(":")
    if not metadata:
        logger.warning("Nickname handler metadata missing for user %s", user.id)
        await active_message_handler_registry.delete(user_id=user.id)
        return

    try:
        panel_message_id = int(metadata)
    except ValueError:
        logger.warning("Invalid nickname handler metadata '%s' for user %s", metadata, user.id)
        await active_message_handler_registry.delete(user_id=user.id)
        return

    submitted = message.text.strip()
    if submitted == "-":
        new_value: str | None = None
    else:
        new_value = submitted

    await user_registry.set_nick_name(user.id, new_value)
    await active_message_handler_registry.delete(user_id=user.id)

    await refresh_user_config_panel(
        context,
        chat_id=message.chat_id,
        message_id=panel_message_id,
        user_id=user.id,
    )

    feedback = "昵称已清除" if new_value is None else "昵称已更新"
    await context.bot.send_message(chat_id=message.chat_id, text=feedback)
