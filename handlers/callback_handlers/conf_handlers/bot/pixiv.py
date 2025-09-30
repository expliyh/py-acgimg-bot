"""Callback helpers for configuring Pixiv API credentials via inline menus."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry, config_registry

from .panel import refresh_bot_config_panel

_PROMPT_TEXT = (
    "请发送新的 Pixiv Refresh Token。\n"
    "若需清除，请发送单个减号 - 。"
)


async def _get_status() -> tuple[str | None, bool]:
    tokens = await config_registry.get_pixiv_tokens()
    token = tokens[0] if tokens else None
    token_value = (token.token or "").strip() if token and token.token else None
    enabled = bool(token.enable) if token else False
    return token_value, enabled


def _build_menu(token: str | None, enabled: bool) -> InlineKeyboardMarkup:
    token_present = bool(token)
    rows: list[list[InlineKeyboardButton]] = []

    rows.append(
        [
            InlineKeyboardButton(
                "设置 Refresh Token" if not token_present else "更新 Refresh Token",
                callback_data="conf:bot:pixiv:set_token",
            )
        ]
    )

    if token_present:
        rows.append(
            [
                InlineKeyboardButton(
                    "清除 Refresh Token",
                    callback_data="conf:bot:pixiv:clear_token",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "禁用 Pixiv 功能" if enabled else "启用 Pixiv 功能",
                callback_data="conf:bot:pixiv:disable" if enabled else "conf:bot:pixiv:enable",
            )
        ]
    )

    rows.append([InlineKeyboardButton("返回", callback_data="conf:bot:panel:refresh")])
    return InlineKeyboardMarkup(rows)


async def handle_pixiv(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or not cmd:
        return

    action = cmd[0]
    token_value, enabled = await _get_status()

    if action == "menu":
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            reply_markup=_build_menu(token_value, enabled),
        )
        await query.answer("已打开 Pixiv 配置")
        return

    if action == "set_token":
        await active_message_handler_registry.set(
            user_id=update.effective_user.id,
            handler_id=f"set_pixiv_token:{update.effective_message.message_id}",
        )
        await query.answer("请输入新的 Refresh Token")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=_PROMPT_TEXT)
        return

    if action == "clear_token":
        await config_registry.set_pixiv_token(None)
        await config_registry.set_pixiv_token_enabled(False)
        await query.answer("已清除并禁用 Pixiv 功能")
        await refresh_bot_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
        )
        return

    if action == "enable":
        if not token_value:
            await query.answer("请先设置 Refresh Token", show_alert=True)
            return
        await config_registry.set_pixiv_token_enabled(True)
        await query.answer("Pixiv 功能已启用")
        await refresh_bot_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
        )
        return

    if action == "disable":
        await config_registry.set_pixiv_token_enabled(False)
        await query.answer("Pixiv 功能已禁用")
        await refresh_bot_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
        )
        return

    await query.answer()
