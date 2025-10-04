"""Entry point for group configuration callback handling."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.panel_utils import close_panel
from registries import group_registry
from services.telegram_cache import get_cached_admin_ids

from .chat_placeholder import handle_chat_placeholder
from .enable import handle_enable_toggle
from .panel import refresh_group_config_panel
from .r18 import handle_r18_toggle
from .setu import handle_setu_toggle


def _parse_command_message_id(cmd_parts: list[str]) -> int | None:
    if not cmd_parts:
        return None
    candidate = cmd_parts[-1]
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return None


def _extract_args(cmd_parts: list[str]) -> tuple[int | None, list[str]]:
    if len(cmd_parts) <= 2:
        return None, []
    candidate = cmd_parts[-1]
    try:
        command_message_id = int(candidate)
    except (TypeError, ValueError):
        return None, cmd_parts[2:]
    return command_message_id, cmd_parts[2:-1]


_HANDLER_MAP = {
    "enable": handle_enable_toggle,
    "r18": handle_r18_toggle,
    "setu": handle_setu_toggle,
    "chat": handle_chat_placeholder,
}


async def group_conf_handler_func(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]
):
    query = update.callback_query
    if query is None or not cmd:
        return

    chat = update.effective_chat
    if chat is None:
        await query.answer()
        return

    try:
        group_id = int(cmd[0])
    except (TypeError, ValueError):
        await query.answer("无法识别的群组", show_alert=True)
        return

    if chat.id != group_id:
        await query.answer("无效的群组操作", show_alert=True)
        return

    group = await group_registry.get_group_by_id(group_id)
    admin_ids = set(group.admin_ids or [])
    if not admin_ids:
        fetched_admin_ids = await get_cached_admin_ids(context, chat.id)
        if fetched_admin_ids:
            admin_ids = set(fetched_admin_ids)

    user = update.effective_user
    user_id = getattr(user, "id", None)
    if user_id is None:
        await query.answer("无法识别的用户", show_alert=True)
        return

    if not admin_ids or user_id not in admin_ids:
        await query.answer("只有群组管理员可以执行此操作", show_alert=True)
        return

    if len(cmd) == 1:
        await query.answer()
        return

    section = cmd[1]

    if section == "panel" and len(cmd) > 2:
        action = cmd[2]
        command_message_id = _parse_command_message_id(cmd)
        if action == "refresh":
            await refresh_group_config_panel(
                context,
                chat_id=chat.id,
                message_id=update.effective_message.message_id,
                group_id=group_id,
                command_message_id=command_message_id,
            )
            await query.answer("已刷新")
            return
        if action == "close":
            await close_panel(
                update,
                context,
                command_message_id=command_message_id,
            )
            return

    handler = _HANDLER_MAP.get(section)
    if handler is None:
        await query.answer()
        return

    command_message_id, args = _extract_args(cmd)

    await handler(
        update,
        context,
        group_id=group_id,
        args=args,
        command_message_id=command_message_id,
    )
