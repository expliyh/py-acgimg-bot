"""Message handler for adding guard keyword rules via chat."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, filters

from handlers.callback_handlers.conf_handlers.group_conf_handlers.panel import (
    refresh_group_config_panel,
)
from registries import active_message_handler_registry
from services import group_guard
from handlers.registry import message_handler

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "guard_add_keyword"
_CANCEL_TOKENS = {"-", "取消", "cancel"}


@message_handler(filters=filters.TEXT & ~filters.COMMAND)
async def guard_add_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if message is None or user is None or chat is None or not message.text:
        return

    handler_key = await active_message_handler_registry.get(user.id, group_id=chat.id)
    if not handler_key or not handler_key.startswith(_HANDLER_PREFIX):
        return

    _, _, metadata = handler_key.partition(":")
    try:
        panel_message_id = int(metadata)
    except (TypeError, ValueError):
        logger.warning("Guard add keyword metadata missing for user %s", user.id)
        await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)
        return

    submitted = message.text.strip()

    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=message.id)
    except TelegramError:
        logger.debug("Failed to delete guard keyword message for user %s", user.id)

    if submitted.lower() in _CANCEL_TOKENS:
        await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)
        await context.bot.send_message(chat_id=chat.id, text="已取消添加关键字")
        return

    tokens = submitted.split()
    pattern_parts: list[str] = []
    is_regex = False
    case_sensitive = False

    for token in tokens:
        lowered = token.lower()
        if lowered in {"--regex", "--re"}:
            is_regex = True
            continue
        if lowered in {"--case", "--case-sensitive"}:
            case_sensitive = True
            continue
        pattern_parts.append(token)

    pattern = " ".join(pattern_parts).strip()
    if not pattern:
        await context.bot.send_message(chat_id=chat.id, text="关键字不能为空，请重新输入")
        return

    try:
        rule = await group_guard.add_keyword_rule(
            chat.id,
            pattern,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
        )
    except ValueError as exc:
        await context.bot.send_message(chat_id=chat.id, text=str(exc))
        return

    await active_message_handler_registry.delete(user_id=user.id, group_id=chat.id)

    await refresh_group_config_panel(
        context,
        chat_id=chat.id,
        message_id=panel_message_id,
        group_id=chat.id,
    )

    flags = []
    if rule.is_regex:
        flags.append("regex")
    if rule.case_sensitive:
        flags.append("case")
    suffix = f" ({', '.join(flags)})" if flags else ""
    await context.bot.send_message(
        chat_id=chat.id,
        text=f"已添加关键字规则 #{rule.id}: {rule.pattern}{suffix}",
    )
