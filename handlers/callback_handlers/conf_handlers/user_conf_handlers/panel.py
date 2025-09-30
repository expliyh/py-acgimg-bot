"""Utilities for refreshing the Telegram user configuration panel."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import messase_generator
from registries import user_registry

logger = logging.getLogger(__name__)


async def refresh_user_config_panel(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    user_id: int,
) -> None:
    """Re-render the user configuration panel in place."""

    user = await user_registry.get_user_by_id(user_id)
    panel = await messase_generator.config_user(user=user)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=panel.text,
        )
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=InlineKeyboardMarkup(panel.keyboard),
        )
    except TelegramError as exc:
        logger.warning(
            "Failed to refresh user config panel for chat %s message %s: %s",
            chat_id,
            message_id,
            exc,
        )
