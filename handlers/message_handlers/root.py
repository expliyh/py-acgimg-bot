"""Root message handler dispatching to the message logging service."""

from telegram import Update
from telegram.ext import ContextTypes

from services.message_logging import log_message_update


async def handle_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist chat metadata and history for every incoming message."""

    await log_message_update(update, context)


# Backwards compatibility for modules importing ``root``
root = handle_incoming_message
