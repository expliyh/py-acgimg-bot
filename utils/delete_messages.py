import asyncio
import logging

from telegram.error import TelegramError
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def delete_messages(
        message_ids: list[int], chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        delay: float) -> None:
    await asyncio.sleep(delay)
    for message_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramError:
            logger.debug("Failed to delete message %s in chat %s", message_id, chat_id, exc_info=True)
    return
