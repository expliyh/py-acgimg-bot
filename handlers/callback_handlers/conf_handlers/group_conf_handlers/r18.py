"""Callback helpers for toggling group R18 allowances."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from registries import group_registry

from .panel import refresh_group_config_panel

_R18_SANITY_LIMIT = 7
_DEFAULT_SANITY_LIMIT = 5


async def handle_r18_toggle(
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

    allow_r18 = action == "on"
    sanity_limit = _R18_SANITY_LIMIT if allow_r18 else _DEFAULT_SANITY_LIMIT

    await group_registry.set_group_sanity_limit(group_id, sanity_limit)

    await query.answer("已允许 R18" if allow_r18 else "已禁止 R18")

    await refresh_group_config_panel(
        context,
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        group_id=group_id,
        command_message_id=command_message_id,
    )
