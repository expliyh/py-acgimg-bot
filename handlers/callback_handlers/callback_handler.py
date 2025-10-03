from telegram import Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.conf_handlers.conf_handler import callback_conf_handler_func
from .original_image_handler import callback_original_image_handler

handler_map = {
    "conf": callback_conf_handler_func,
    "orig": callback_original_image_handler,
}


async def callback_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch callback queries to the appropriate handler."""
    query = update.callback_query
    if query is None or not query.data:
        return

    parts = query.data.split(":")
    command = parts[0]
    handler = handler_map.get(command)
    if handler is None:
        await query.answer("未知的请求", show_alert=True)
        return

    await handler(update, context, parts[1:])
