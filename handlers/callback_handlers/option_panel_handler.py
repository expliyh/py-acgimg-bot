"""Callback handler for choosing where to open the configuration panel."""

from __future__ import annotations

import logging
from typing import Iterable

import messase_generator
from telegram import InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from handlers.callback_handlers.panel_utils import register_panel
from registries import group_registry

logger = logging.getLogger(__name__)


def build_option_callback_data(
    target: str,
    group_id: int,
    user_id: int,
    command_message_id: int | None,
) -> str:
    """Compose callback data for group option panel location selections."""

    parts: list[str | int] = ["option", target, group_id, user_id]
    if command_message_id is not None:
        parts.append(command_message_id)
    return ":".join(str(part) for part in parts)


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def option_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, parts: Iterable[str]
) -> None:
    """Handle location selection for the configuration panel."""

    query = update.callback_query
    if query is None:
        return

    parts = list(parts)
    if len(parts) < 3:
        await query.answer("无法识别的请求", show_alert=True)
        return

    target = parts[0]
    group_id = _parse_int(parts[1])
    expected_user_id = _parse_int(parts[2])
    command_message_id = _parse_int(parts[3]) if len(parts) > 3 else None

    if group_id is None or expected_user_id is None:
        await query.answer("无效的参数", show_alert=True)
        return

    user = update.effective_user
    user_id = getattr(user, "id", None)
    if user_id != expected_user_id:
        await query.answer("仅命令发起者可以执行此操作", show_alert=True)
        return

    try:
        group = await group_registry.get_group_by_id(group_id)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Failed to load group %s: %s", group_id, exc)
        await query.answer("无法载入群组信息", show_alert=True)
        return

    if group is None:
        await query.answer("未找到群组信息", show_alert=True)
        return

    chat = update.effective_chat

    if target == "group":
        if chat is None or chat.id != group_id:
            await query.answer("无法在此打开面板", show_alert=True)
            return

        panel = await messase_generator.config_group(
            group=group, command_message_id=command_message_id
        )

        message = await context.bot.send_message(
            chat_id=chat.id,
            text=panel.text,
            reply_markup=InlineKeyboardMarkup(panel.keyboard),
        )

        register_panel(context, message.message_id, command_message_id)

        try:
            await context.bot.delete_message(
                chat_id=chat.id, message_id=update.effective_message.message_id
            )
        except TelegramError as exc:  # pragma: no cover - best effort cleanup
            logger.debug(
                "Failed to delete option selection message in chat %s: %s",
                chat.id,
                exc,
            )

        await query.answer("已在群组中打开控制面板")
        return

    if target == "private":
        panel = await messase_generator.config_group(group=group, command_message_id=None)

        try:
            private_message = await context.bot.send_message(
                chat_id=expected_user_id,
                text=panel.text,
                reply_markup=InlineKeyboardMarkup(panel.keyboard),
            )
        except Forbidden:
            await query.answer("请先私聊机器人后再尝试", show_alert=True)
            return
        except TelegramError as exc:
            logger.warning(
                "Failed to send private option panel for group %s to user %s: %s",
                group_id,
                expected_user_id,
                exc,
            )
            await query.answer("无法发送私聊消息", show_alert=True)
            return

        register_panel(
            context,
            private_message.message_id,
            None,
            chat_id=expected_user_id,
        )

        if chat is not None:
            try:
                await context.bot.delete_message(
                    chat_id=chat.id, message_id=update.effective_message.message_id
                )
            except TelegramError as exc:  # pragma: no cover - best effort cleanup
                logger.debug(
                    "Failed to delete option selection message in chat %s: %s",
                    chat.id,
                    exc,
                )

        await query.answer("已在私聊中发送控制面板")
        return

    await query.answer()

