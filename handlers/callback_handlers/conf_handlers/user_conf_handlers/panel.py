"""Utilities for refreshing the Telegram user configuration panel."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from handlers.callback_handlers.panel_utils import get_panel_command_message_id, register_panel
import messase_generator
from registries import user_registry

logger = logging.getLogger(__name__)


async def refresh_user_config_panel(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    user_id: int,
    command_message_id: int | None = None,
) -> None:
    """Re-render the user configuration panel in place."""

    user = await user_registry.get_user_by_id(user_id)
    if command_message_id is None:
        command_message_id = get_panel_command_message_id(context, message_id)
    panel = await messase_generator.config_user(user=user, command_message_id=command_message_id)

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
        register_panel(context, message_id, command_message_id)
    except TelegramError as exc:
        logger.warning(
            "Failed to refresh user config panel for chat %s message %s: %s",
            chat_id,
            message_id,
            exc,
        )
