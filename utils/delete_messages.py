import asyncio

from telegram.ext import ContextTypes


async def delete_messages(
        message_ids: list[int], chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        delay: float) -> None:
    await asyncio.sleep(delay)
    for message_id in message_ids:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    return
