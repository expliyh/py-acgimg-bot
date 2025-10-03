"""Placeholder handler for the unimplemented AI chat toggle."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


async def handle_chat_placeholder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    group_id: int,
    args: list[str],
    command_message_id: int | None,
) -> None:
    del context, group_id, args, command_message_id

    query = update.callback_query
    if query is None:
        return

    await query.answer("AI 聊天功能暂未实现", show_alert=True)
