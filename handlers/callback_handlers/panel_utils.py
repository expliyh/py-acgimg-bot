"""Utilities for tracking inline panel state and handling closures."""

from __future__ import annotations

import logging
from typing import Any

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from registries import active_message_handler_registry

logger = logging.getLogger(__name__)

_PANEL_MAP_KEY = "__panel_command_map__"


def build_callback_data(base: str, command_message_id: int | None) -> str:
    """Append the originating command message ID to callback data when available."""

    if command_message_id is None:
        return base
    return f"{base}:{command_message_id}"


def register_panel(context: ContextTypes.DEFAULT_TYPE, panel_message_id: int, command_message_id: int | None) -> None:
    """Store the originating command message for a rendered panel message."""

    mapping = _ensure_panel_map(context)
    mapping[panel_message_id] = command_message_id


def unregister_panel(context: ContextTypes.DEFAULT_TYPE, panel_message_id: int) -> None:
    mapping = context.chat_data.get(_PANEL_MAP_KEY)
    if isinstance(mapping, dict):
        mapping.pop(panel_message_id, None)


def get_panel_command_message_id(
    context: ContextTypes.DEFAULT_TYPE, panel_message_id: int
) -> int | None:
    mapping = context.chat_data.get(_PANEL_MAP_KEY)
    if isinstance(mapping, dict):
        command_message_id = mapping.get(panel_message_id)
        if isinstance(command_message_id, int):
            return command_message_id
    return None


def _ensure_panel_map(context: ContextTypes.DEFAULT_TYPE) -> dict[int, int | None]:
    mapping = context.chat_data.get(_PANEL_MAP_KEY)
    if not isinstance(mapping, dict):
        mapping = {}
        context.chat_data[_PANEL_MAP_KEY] = mapping
    return mapping


def _parse_command_id(command_message_id: int | None, context: ContextTypes.DEFAULT_TYPE, panel_message_id: int | None) -> int | None:
    if command_message_id is not None:
        return command_message_id
    if panel_message_id is None:
        return None
    return get_panel_command_message_id(context, panel_message_id)


async def close_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int | None = None,
    command_message_id: int | None = None,
    ack_text: str = "已关闭"
) -> None:
    """Close a configuration panel and delete its originating command message."""

    query = update.callback_query
    panel_message = update.effective_message
    chat = update.effective_chat

    panel_message_id = getattr(panel_message, "message_id", None)
    resolved_command_id = _parse_command_id(command_message_id, context, panel_message_id)

    if user_id is not None:
        await active_message_handler_registry.delete(user_id=user_id)

    if panel_message_id is not None:
        unregister_panel(context, panel_message_id)

    if chat is None:
        if query is not None:
            await query.answer(ack_text)
        return

    chat_id = chat.id

    if panel_message_id is not None:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=panel_message_id)
        except TelegramError as exc:
            logger.warning("Failed to delete panel message %s in chat %s: %s", panel_message_id, chat_id, exc)

    if resolved_command_id is not None:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=resolved_command_id)
        except TelegramError as exc:
            logger.warning(
                "Failed to delete originating command message %s in chat %s: %s",
                resolved_command_id,
                chat_id,
                exc,
            )

    if query is not None:
        await query.answer(ack_text)

