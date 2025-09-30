"""Callback helpers for adjusting a user's sanity limit."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import messase_generator
from registries import user_registry

from .panel import refresh_user_config_panel

_LEVELS = tuple(range(0, 7))


def _chunked(items: tuple[int, ...], size: int) -> list[list[int]]:
    rows: list[list[int]] = []
    for index in range(0, len(items), size):
        rows.append(list(items[index : index + size]))
    return rows


def _build_picker(current_level: int) -> InlineKeyboardMarkup:
    rows = []
    for chunk in _chunked(_LEVELS, 3):
        row = []
        for level in chunk:
            label = f"L{level}"
            if level == current_level:
                label = f"▷ L{level} ◁"
            row.append(InlineKeyboardButton(label, callback_data=f"conf:user:san:set:{level}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("取消", callback_data="conf:user:san:cancel")])
    return InlineKeyboardMarkup(rows)


async def handle_sanity(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or not cmd:
        return

    action = cmd[0]
    user = await user_registry.get_user_by_id(update.effective_user.id)
    current_level = max(user.sanity_limit - 1, 0)

    if action == "edit":
        panel = await messase_generator.config_user(user=user)
        instruction = f"{panel.text}\n\n请选择新的过滤等级："
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            text=instruction,
        )
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            reply_markup=_build_picker(current_level),
        )
        await query.answer()
        return

    if action == "cancel":
        await query.answer("已取消")
        await refresh_user_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            user_id=user.id,
        )
        return

    if action == "set" and len(cmd) >= 2:
        try:
            level = int(cmd[1])
        except ValueError:
            await query.answer("无效的过滤等级", show_alert=True)
            return

        level = max(0, min(level, max(_LEVELS)))
        await user_registry.set_sanity_limit(user.id, level + 1)
        await query.answer(f"已设置为 L{level}")
        await refresh_user_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            user_id=user.id,
        )
        return

    await query.answer()
