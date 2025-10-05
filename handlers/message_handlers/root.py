"""Root message handler used for logging incoming updates."""

from __future__ import annotations

import logging

from telegram import Message, Update, User as TgUser
from telegram.ext import ContextTypes

from handlers.registry import message_handler_foreach
from services.message_logging import log_message_update

logger = logging.getLogger(__name__)

MAX_TEXT_PREVIEW_LENGTH = 120


def _display_user(user: TgUser | None) -> str:
    if user is None:
        return "unknown"

    for candidate in (
        user.full_name,
        user.username,
        user.first_name,
        user.last_name,
    ):
        if candidate:
            return candidate

    return str(user.id)


def _preview_text(text: str | None, limit: int = MAX_TEXT_PREVIEW_LENGTH) -> str | None:
    if not text:
        return None

    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized

    return normalized[:limit] + "..."


def _describe_attachments(message: Message) -> str:
    attachment = message.effective_attachment
    descriptors: list[str] = []

    if attachment is not None:
        if isinstance(attachment, list):
            if attachment:
                descriptors.append(f"{type(attachment[0]).__name__}[{len(attachment)}]")
        else:
            descriptors.append(type(attachment).__name__)

    if message.new_chat_members:
        descriptors.append(f"new_members={len(message.new_chat_members)}")
    if message.left_chat_member:
        descriptors.append("left_chat_member=1")
    if message.pinned_message:
        descriptors.append("pinned_message=1")

    if not descriptors:
        return "none"

    return ",".join(descriptors)


def _describe_message(message: Message | None) -> str:
    if message is None:
        return "no-message"

    parts = [
        f"id={message.message_id}",
    ]

    if message.date:
        parts.append(f"date={message.date.isoformat()}")

    preview = _preview_text(message.text or message.caption)
    if preview:
        parts.append(f'text="{preview}"')

    attachments = _describe_attachments(message)
    if attachments != "none":
        parts.append(f"attachments={attachments}")

    if message.via_bot:
        parts.append("via_bot=1")

    return ", ".join(parts)


async def handle_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log metadata for every incoming message and persist history."""

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    logger.debug(
        "Update received chat_id=%s chat_type=%s user_id=%s user=%s summary=%s",
        chat.id if chat else None,
        chat.type if chat else None,
        user.id if user else None,
        _display_user(user),
        _describe_message(message),
    )

    await message_handler_foreach(update, context)

    await log_message_update(update, context)


# Backwards compatibility for modules importing ``root``
root = handle_incoming_message
