"""Callback helpers for updating a user's nickname."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry

from .panel import refresh_user_config_panel

_PROMPT_TEXT = (
    "请发送新的昵称（不超过 64 个字符）。\n"
    "如果要清除昵称，请发送单个减号 - 。"
)


async def handle_nick(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or not cmd:
        return

    action = cmd[0]
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    panel_message_id = update.effective_message.message_id

    if action == "edit":
        await active_message_handler_registry.set(
            user_id=user_id,
            handler_id=f"set_user_nickname:{panel_message_id}",
        )
        await query.answer("请输入新的昵称")
        await context.bot.send_message(chat_id=chat_id, text=_PROMPT_TEXT)
        return

    if action == "cancel":
        await active_message_handler_registry.delete(user_id=user_id)
        await query.answer("已取消")
        await refresh_user_config_panel(
            context,
            chat_id=chat_id,
            message_id=panel_message_id,
            user_id=user_id,
        )
        return

    await query.answer()
