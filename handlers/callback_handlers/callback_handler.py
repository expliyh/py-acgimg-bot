from telegram import Update
from telegram.ext import ContextTypes


async def callback_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理用户回调
    :param update:
    :param context:
    :return: None
    """
    query = update.callback_query
    cmd = query.data.split(":")
    pass
