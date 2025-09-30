import asyncio

from telegram import Update, Message, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes
from telegram.constants import ParseMode

import messase_generator
from utils import is_group_type, delete_messages
from registries import user_registry, group_registry, engine
from services.command_history import command_logger


@command_logger("admin")
async def admin_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理机器人管理命令
    :param update:
    :param context:
    :return: None
    """
    is_group = is_group_type(update.effective_chat.type)
    user = await user_registry.get_user_by_id(update.effective_user.id)
    if is_group:
        message: Message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="请不要在群组中使用此命令 (该提示和命令将在 10 秒后自动删除)",
            reply_to_message_id=update.effective_message.id
        )
        await asyncio.create_task(delete_messages(
            chat_id=update.effective_chat.id,
            message_ids=[update.effective_message.id, message.message_id],
            context=context,
            delay=10
        ))
        return
    config = await messase_generator.bot_admin(page=1)

    message: Message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=config.text,
        reply_markup=InlineKeyboardMarkup(config.keyboard),
        parse_mode=ParseMode.MARKDOWN_V2
    )
    return


admin_handler = CommandHandler('admin', admin_handler_func)
