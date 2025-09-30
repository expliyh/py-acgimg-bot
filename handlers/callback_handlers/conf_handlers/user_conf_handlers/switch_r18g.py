"""Callback helpers for switching a user's R18G preference."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from registries import user_registry

from .panel import refresh_user_config_panel

_WARNING_TEXT = (
    "警告：启用 R18G 将允许在涩图请求中返回极度限制级内容。\n"
    "请确认您已年满 18 岁并理解可能出现的风险。"
)


async def _apply(update: Update, context: ContextTypes.DEFAULT_TYPE, enable: bool) -> None:
    user_id = update.effective_user.id
    await user_registry.set_allow_r18g(user_id, enable)

    query = update.callback_query
    if query is not None:
        await query.answer("已启用 R18G" if enable else "已禁用 R18G")

    await refresh_user_config_panel(
        context,
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        user_id=user_id,
    )


async def _show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        text=_WARNING_TEXT,
    )
    await context.bot.edit_message_reply_markup(
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("确认启用", callback_data="conf:user:r18g:confirm")],
                [InlineKeyboardButton("取消", callback_data="conf:user:r18g:cancel")],
            ]
        ),
    )

    query = update.callback_query
    if query is not None:
        await query.answer()


async def switch_r18g(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or not cmd:
        return

    action = cmd[0]

    if action == "off":
        await _apply(update, context, False)
        return

    if action == "on":
        await _show_confirmation(update, context)
        return

    if action == "confirm":
        await _apply(update, context, True)
        return

    if action == "cancel":
        await query.answer("已取消")
        await refresh_user_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            user_id=update.effective_user.id,
        )
        return

    await query.answer()
