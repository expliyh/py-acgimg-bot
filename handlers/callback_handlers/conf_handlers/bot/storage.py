"""Callback helpers for selecting the storage backend."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.panel_utils import build_callback_data, get_panel_command_message_id
from registries import config_registry

from .panel import refresh_bot_config_panel

_STORAGE_OPTIONS = [
    ("local", "本地存储"),
    ("backblaze", "Backblaze B2"),
    ("webdav", "WebDAV"),
    ("disabled", "禁用存储"),
]


def _storage_label(value: str | None) -> str:
    if value is None:
        return "未设置"
    value = value.lower()
    for key, label in _STORAGE_OPTIONS:
        if key == value:
            return label
    if value in {"none"}:
        return "未设置"
    return value


def _build_menu(current: str | None, *, command_message_id: int | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, label in _STORAGE_OPTIONS:
        suffix = " ✅" if current and current.lower() == key else ""
        rows.append([
            InlineKeyboardButton(
                f"{label}{suffix}",
                callback_data=f"conf:bot:storage:set:{key}",
            )
        ])
    rows.append([InlineKeyboardButton("返回", callback_data=build_callback_data("conf:bot:panel:refresh", command_message_id))])
    return InlineKeyboardMarkup(rows)


async def handle_storage(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or not cmd:
        return

    action = cmd[0]
    current = await config_registry.get_config("storage_service_use")
    if isinstance(current, str):
        current = current.strip().lower() or None

    panel_message_id = update.effective_message.message_id
    command_message_id = get_panel_command_message_id(context, panel_message_id)

    if action == "menu":
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=panel_message_id,
            reply_markup=_build_menu(current, command_message_id=command_message_id),
        )
        await query.answer("请选择存储驱动")
        return

    if action == "set" and len(cmd) >= 2:
        choice = cmd[1].lower()
        if choice not in {key for key, _ in _STORAGE_OPTIONS}:
            await query.answer("不支持的存储驱动", show_alert=True)
            return

        await config_registry.update_config("storage_service_use", choice)
        await query.answer(f"已切换到 {_storage_label(choice)}")
        await refresh_bot_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=panel_message_id,
            command_message_id=command_message_id,
        )
        return

    if action == "cancel":
        await query.answer("已取消")
        await refresh_bot_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=panel_message_id,
            command_message_id=command_message_id,
        )
        return

    await query.answer()
