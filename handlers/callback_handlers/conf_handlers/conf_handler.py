from telegram import Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.conf_handlers.bot.bot_conf_handler import bot_conf_handler_func
from handlers.callback_handlers.conf_handlers.user_conf_handlers import user_conf_handler_func

handler_map = {
    "user": user_conf_handler_func,
    "bot": bot_conf_handler_func,
}


async def callback_conf_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]):
    if not cmd:
        return

    handler = handler_map.get(cmd[0])
    if handler is None:
        query = update.callback_query
        if query is not None:
            await query.answer()
        return

    return await handler(update, context, cmd[1:])
