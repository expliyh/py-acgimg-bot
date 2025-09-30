"""Callback helpers for toggling a user's AI chat setting."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from registries import user_registry

from .panel import refresh_user_config_panel


async def handle_chat_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or not cmd:
        return

    action = cmd[0]
    if action not in {"on", "off"}:
        await query.answer()
        return

    user_id = update.effective_user.id
    enable = action == "on"

    await user_registry.set_enable_chat(user_id, enable)

    await query.answer("AI 聊天已启用" if enable else "AI 聊天已禁用")

    await refresh_user_config_panel(
        context,
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        user_id=user_id,
    )
