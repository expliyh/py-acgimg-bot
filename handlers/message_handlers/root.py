"""Root message handler dispatching to the message logging service."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry
from services.message_logging import log_message_update
from utils import is_group_type

from .set_backblaze_appid import set_backblaze_appid
from .set_user_nickname import set_user_nickname
from .set_pixiv_token import set_pixiv_token

_MESSAGE_HANDLERS = {
    "set_backblaze_appid": set_backblaze_appid,
    "set_user_nickname": set_user_nickname,
    "set_pixiv_token": set_pixiv_token,
}


async def handle_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist chat metadata and history for every incoming message and dispatch flows."""

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if message is not None and chat is not None and user is not None:
        group_id = chat.id if is_group_type(chat.type) else 0
        handler_key = await active_message_handler_registry.get(user.id, group_id=group_id)

        if handler_key:
            handler_name, _, _ = handler_key.partition(":")
            handler = _MESSAGE_HANDLERS.get(handler_name)
            if handler is not None:
                await handler(update, context)

    await log_message_update(update, context)


# Backwards compatibility for modules importing ``root``
root = handle_incoming_message
