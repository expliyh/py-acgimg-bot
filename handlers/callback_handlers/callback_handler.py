from telegram import Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.conf_handlers.conf_handler import callback_conf_handler_func

handler_map = {
    "conf": callback_conf_handler_func
}


async def callback_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理用户回调
    :param update:
    :param context:
    :return: None
    """
    query = update.callback_query
    cmd = query.data.split(":")
    return await callback_conf_handler_func(update, context, cmd[1:])
