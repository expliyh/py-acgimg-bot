"""Callback helpers for toggling global feature flags."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.panel_utils import get_panel_command_message_id
from registries import config_registry

from .panel import refresh_bot_config_panel

_MUTABLE_FLAGS = {
    "allow_r18g": ("允许 R18G", "已允许", "已禁用"),
    "enable_on_new_group": ("新群自动启用", "默认启用", "默认关闭"),
}


def _is_truthy(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return False


async def handle_feature_flag(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or len(cmd) < 2:
        return

    key = cmd[0]
    action = cmd[1]

    if key not in _MUTABLE_FLAGS:
        await query.answer("未知的配置项", show_alert=True)
        return

    current_value = _is_truthy(await config_registry.get_config(key))

    if action == "toggle":
        new_value = not current_value
    elif action == "on":
        new_value = True
    elif action == "off":
        new_value = False
    else:
        await query.answer()
        return

    await config_registry.update_config(key, new_value)

    label, enabled_text, disabled_text = _MUTABLE_FLAGS[key]
    await query.answer(f"{label} {enabled_text if new_value else disabled_text}")

    panel_message_id = update.effective_message.message_id
    command_message_id = get_panel_command_message_id(context, panel_message_id)

    await refresh_bot_config_panel(
        context,
        chat_id=update.effective_chat.id,
        message_id=panel_message_id,
        command_message_id=command_message_id,
    )
