import asyncio

from telegram import Update, Message, InlineKeyboardMarkup, InlineKeyboardButton

import messase_generator
from utils import is_group_type, delete_messages
from registries import user_registry, group_registry
from handlers.callback_handlers.panel_utils import register_panel
from handlers.callback_handlers.option_panel_handler import (
    build_option_callback_data,
)
from services.command_history import command_logger
from handlers.registry import bot_handler
from services.telegram_cache import get_cached_admin_ids


@bot_handler
@command_logger("option")
async def option_handler_func(update: Update, context) -> None:
    """
    处理用户配置命令
    :param update:
    :param context:
    :return: None
    """
    is_group = is_group_type(update.effective_chat.type)
    user = await user_registry.get_user_by_id(update.effective_user.id)
    command_message = update.effective_message
    command_message_id = getattr(command_message, "message_id", None)

    if is_group:
        chat_id = update.effective_chat.id
        group = await group_registry.get_group_by_id(chat_id)
        admin_ids = set(group.admin_ids or [])
        if not admin_ids:
            fetched_admin_ids = await get_cached_admin_ids(context, chat_id)
            if fetched_admin_ids:
                admin_ids = set(fetched_admin_ids)

        if not admin_ids or user.id not in admin_ids:
            # 回复命令提示没有权限并定时删除回复和命令
            message: Message = await context.bot.send_message(
                chat_id=chat_id,
                text="您没有权限使用此命令 (该提示和命令将在 10 秒后自动删除)",
                reply_to_message_id=update.effective_message.id
            )
            await asyncio.create_task(delete_messages(
                chat_id=chat_id,
                message_ids=[update.effective_message.id, message.message_id],
                context=context,
                delay=10
            ))
            return
        selection_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "在此处打开控制面板",
                        callback_data=build_option_callback_data(
                            "group", group.id, user.id, command_message_id
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "在私聊中打开控制面板",
                        callback_data=build_option_callback_data(
                            "private", group.id, user.id, command_message_id
                        ),
                    )
                ],
            ]
        )

        send_kwargs = {
            "chat_id": update.effective_chat.id,
            "text": "请选择在何处打开控制面板",
            "reply_markup": selection_keyboard,
        }
        if command_message_id is not None:
            send_kwargs["reply_to_message_id"] = command_message_id

        await context.bot.send_message(**send_kwargs)
        return

    config = await messase_generator.config_user(page=1, user=user, command_message_id=command_message_id)

    message: Message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=config.text,
        reply_markup=InlineKeyboardMarkup(config.keyboard)
    )

    register_panel(context, message.message_id, command_message_id)
    return

