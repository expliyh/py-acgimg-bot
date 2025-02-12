from telegram import Update
from telegram.ext import ContextTypes

from .switch_r18g import switch_r18g

handler_map = {
    "r18g": switch_r18g
}


async def user_conf_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="UserOptionCallback!"
    )
    return await handler_map[cmd[0]](update, context, cmd[1:])
