"""Callback helpers for toggling group enablement."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from registries import group_registry

from .panel import refresh_group_config_panel


async def handle_enable_toggle(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    group_id: int,
    args: list[str],
    command_message_id: int | None,
) -> None:
    query = update.callback_query
    if query is None or not args:
        return

    action = args[0]
    if action not in {"on", "off"}:
        await query.answer()
        return

    enable = action == "on"

    await group_registry.set_group_enable(group_id, enable)

    await query.answer("机器人已启用" if enable else "机器人已禁用")

    await refresh_group_config_panel(
        context,
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        group_id=group_id,
        command_message_id=command_message_id,
    )
