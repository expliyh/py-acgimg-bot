"""Utilities for refreshing the Telegram bot admin configuration panel."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import messase_generator

logger = logging.getLogger(__name__)


async def refresh_bot_config_panel(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
) -> None:
    panel = await messase_generator.bot_admin()

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
            "Failed to refresh bot config panel for chat %s message %s: %s",
            chat_id,
            message_id,
            exc,
        )
