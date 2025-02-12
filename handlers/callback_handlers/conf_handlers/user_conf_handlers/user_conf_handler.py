from telegram import Update
from telegram.ext import ContextTypes

handler_map = {

}


async def user_conf_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="UserOptionCallback!"
    )
    # return handler_map[cmd[0]](update, context, cmd[1:])
