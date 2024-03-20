import asyncio

from telegram import Update, Message
from telegram.ext import CommandHandler

import messase_generator
from utils import is_group_type, delete_messages
from registries import user_registry, group_registry


async def option_handler_func(update: Update, context) -> None:
    """
    处理用户配置命令
    :param update:
    :param context:
    :return: None
    """
    is_group = is_group_type(update.effective_chat.type)
    user = await user_registry.get_user_by_id(update.effective_user.id)
    if is_group:
        group = await group_registry.get_group_by_id(update.effective_chat.id)
        if user not in group.admin_ids:
            # 回复命令提示没有权限并定时删除回复和命令
            message: Message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="您没有权限使用此命令 (该提示和命令将在 10 秒后自动删除)",
                reply_to_message_id=update.effective_message.id
            )
            await asyncio.create_task(delete_messages(
                chat_id=update.effective_chat.id,
                message_ids=[update.effective_message.id, message.message_id],
                context=context,
                delay=10
            ))
            return
        return
    config = await messase_generator.config_user(page=1, user=user)
    message: Message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=config.text,
        reply_markup=config.keyboard
    )
    return


option_handler = CommandHandler("option", option_handler_func)
