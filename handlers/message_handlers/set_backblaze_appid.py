"""Message handler for updating Backblaze App ID via chat."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, filters

from handlers.callback_handlers.conf_handlers.bot.panel import refresh_bot_config_panel
from handlers.registry import message_handler
from registries import active_message_handler_registry, config_registry

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "set_backblaze_appid"


@message_handler(filters=filters.TEXT & ~filters.COMMAND)
async def set_backblaze_appid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None or not message.text:
        return

    handler_key = await active_message_handler_registry.get(user.id)
    if not handler_key or not handler_key.startswith(_HANDLER_PREFIX):
        return

    _, _, metadata = handler_key.partition(":")
    panel_message_id: int | None = None
    if metadata:
        try:
            panel_message_id = int(metadata)
        except ValueError:
            logger.warning(
                "Backblaze handler metadata invalid for user %s: %s",
                user.id,
                metadata,
            )

    submitted = message.text.strip()
    update_succeeded = False

    try:
        await config_registry.update_config("backblaze_app_id", submitted)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to update Backblaze App ID for user %s", user.id)
        await context.bot.send_message(
            chat_id=message.chat_id,
            text="Failed to update Backblaze App ID, please try again later",
        )
    else:
        update_succeeded = True
    finally:
        await active_message_handler_registry.delete(user_id=user.id)

    if not update_succeeded:
        return

    try:
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.id)
    except TelegramError:
        logger.debug("Failed to delete Backblaze App ID submission for user %s", user.id)

    if panel_message_id is not None:
        await refresh_bot_config_panel(
            context,
            chat_id=message.chat_id,
            message_id=panel_message_id,
        )

    await context.bot.send_message(
        chat_id=message.chat_id,
        text="BackBlaze App ID updated successfully",
    )
