from telegram import Update
from telegram.ext import ContextTypes

from registries import config_registry, active_message_handler_registry
from handlers.registry import message_handler


@message_handler
async def set_backblaze_appid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    await active_message_handler_registry.delete(
        user_id=update.effective_user.id,
    )
    await config_registry.update_config("backblaze_app_id", message)
    await context.bot.delete_message(message_id=update.effective_message.id, chat_id=update.effective_message.chat_id)
    await context.bot.send_message(
        chat_id=update.effective_message.chat_id,
        text="已成功设置 BackBlaze AppID!",
    )
