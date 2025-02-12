from telegram import Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.conf_handlers.user_conf_handlers import user_conf_handler_func

handler_map = {
    "user": user_conf_handler_func
}


async def callback_conf_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]):
    return handler_map[cmd[0]](update, context, cmd[1:])
