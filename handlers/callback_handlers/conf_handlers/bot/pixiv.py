"""Callback helpers for configuring Pixiv API credentials via inline menus."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry, config_registry
from services import pixiv

from .panel import refresh_bot_config_panel

_PROMPT_ADD = (
    "请发送新的 Pixiv Refresh Token。\n"
    "若要取消，请发送单个减号 -"
)

_PROMPT_UPDATE = (
    "请发送新的 Pixiv Refresh Token 以替换当前值。\n"
    "若要取消，请发送单个减号 -"
)


def _mask_token_value(token: str) -> str:
    text = (token or "").strip()
    if not text:
        return "未设置"
    if len(text) <= 10:
        return text
    return f"{text[:3]}…{text[-4:]}"


def _build_main_menu(tokens: list[config_registry.Token]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    rows.append(
        [InlineKeyboardButton("添加 Refresh Token", callback_data="conf:bot:pixiv:add")]
    )

    for index, token in enumerate(tokens, start=1):
        status = "✅" if token.enable else "🚫"
        label = f"Token #{index} {status} {_mask_token_value(token.token)}"
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"conf:bot:pixiv:token:{token.id}")]
        )

    if tokens:
        if any(not token.enable for token in tokens):
            rows.append(
                [InlineKeyboardButton("启用全部", callback_data="conf:bot:pixiv:enable_all")]
            )
        if any(token.enable for token in tokens):
            rows.append(
                [InlineKeyboardButton("禁用全部", callback_data="conf:bot:pixiv:disable_all")]
            )
        rows.append(
            [InlineKeyboardButton("清除全部", callback_data="conf:bot:pixiv:delete_all")]
        )

    rows.append([InlineKeyboardButton("返回", callback_data="conf:bot:panel:refresh")])
    return InlineKeyboardMarkup(rows)


def _build_token_menu(token: config_registry.Token) -> InlineKeyboardMarkup:
    toggle_label = "禁用 Token" if token.enable else "启用 Token"
    rows = [
        [InlineKeyboardButton("更新 Refresh Token", callback_data=f"conf:bot:pixiv:update:{token.id}")],
        [InlineKeyboardButton(toggle_label, callback_data=f"conf:bot:pixiv:toggle:{token.id}")],
        [InlineKeyboardButton("删除 Token", callback_data=f"conf:bot:pixiv:delete:{token.id}")],
        [InlineKeyboardButton("返回列表", callback_data="conf:bot:pixiv:menu")],
    ]
    return InlineKeyboardMarkup(rows)


async def _reload_pixiv_service(force_refresh: bool = False) -> None:
    await pixiv.read_token_from_config()
    if pixiv.enabled:
        await pixiv.token_refresh(force=force_refresh)


async def handle_pixiv(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or not cmd:
        return

    action = cmd[0]
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if message is None or chat is None or user is None:
        await query.answer("无法处理请求", show_alert=True)
        return

    panel_message_id = message.message_id

    if action == "menu":
        tokens = await config_registry.get_pixiv_tokens()
        await context.bot.edit_message_reply_markup(
            chat_id=chat.id,
            message_id=panel_message_id,
            reply_markup=_build_main_menu(tokens),
        )
        await query.answer("已打开 Pixiv 配置")
        return

    if action == "add":
        await active_message_handler_registry.set(
            user_id=user.id,
            handler_id=f"set_pixiv_token:add:{panel_message_id}:0",
        )
        await query.answer("请输入新的 Refresh Token")
        await context.bot.send_message(chat_id=chat.id, text=_PROMPT_ADD)
        return

    if action == "token" and len(cmd) >= 2:
        token_id = cmd[1]
        tokens = await config_registry.get_pixiv_tokens()
        target = next((item for item in tokens if str(item.id) == token_id), None)
        if target is None:
            await query.answer("未找到对应 Token", show_alert=True)
            return
        await context.bot.edit_message_reply_markup(
            chat_id=chat.id,
            message_id=panel_message_id,
            reply_markup=_build_token_menu(target),
        )
        await query.answer("已打开 Token 配置")
        return

    if action == "update" and len(cmd) >= 2:
        token_id = cmd[1]
        await active_message_handler_registry.set(
            user_id=user.id,
            handler_id=f"set_pixiv_token:update:{panel_message_id}:{token_id}",
        )
        await query.answer("请输入新的 Refresh Token")
        await context.bot.send_message(chat_id=chat.id, text=_PROMPT_UPDATE)
        return

    if action == "toggle" and len(cmd) >= 2:
        token_id = cmd[1]
        tokens = await config_registry.get_pixiv_tokens()
        target = next((item for item in tokens if str(item.id) == token_id), None)
        if target is None or target.id is None:
            await query.answer("未找到对应 Token", show_alert=True)
            return
        await config_registry.set_pixiv_token_enabled(target.id, not target.enable)
        await _reload_pixiv_service()
        updated_tokens = await config_registry.get_pixiv_tokens()
        await context.bot.edit_message_reply_markup(
            chat_id=chat.id,
            message_id=panel_message_id,
            reply_markup=_build_main_menu(updated_tokens),
        )
        await refresh_bot_config_panel(context, chat_id=chat.id, message_id=panel_message_id)
        await query.answer("已更新 Token 状态")
        return

    if action == "delete" and len(cmd) >= 2:
        token_id = cmd[1]
        tokens = await config_registry.get_pixiv_tokens()
        target = next((item for item in tokens if str(item.id) == token_id), None)
        if target is None or target.id is None:
            await query.answer("未找到对应 Token", show_alert=True)
            return
        await config_registry.delete_pixiv_token(target.id)
        await _reload_pixiv_service(force_refresh=True)
        updated_tokens = await config_registry.get_pixiv_tokens()
        await context.bot.edit_message_reply_markup(
            chat_id=chat.id,
            message_id=panel_message_id,
            reply_markup=_build_main_menu(updated_tokens),
        )
        await refresh_bot_config_panel(context, chat_id=chat.id, message_id=panel_message_id)
        await query.answer("已删除 Token")
        return

    if action == "enable_all":
        await config_registry.set_all_pixiv_tokens_enabled(True)
        await _reload_pixiv_service()
        updated_tokens = await config_registry.get_pixiv_tokens()
        await context.bot.edit_message_reply_markup(
            chat_id=chat.id,
            message_id=panel_message_id,
            reply_markup=_build_main_menu(updated_tokens),
        )
        await refresh_bot_config_panel(context, chat_id=chat.id, message_id=panel_message_id)
        await query.answer("已启用全部 Token")
        return

    if action == "disable_all":
        await config_registry.set_all_pixiv_tokens_enabled(False)
        await _reload_pixiv_service()
        updated_tokens = await config_registry.get_pixiv_tokens()
        await context.bot.edit_message_reply_markup(
            chat_id=chat.id,
            message_id=panel_message_id,
            reply_markup=_build_main_menu(updated_tokens),
        )
        await refresh_bot_config_panel(context, chat_id=chat.id, message_id=panel_message_id)
        await query.answer("已禁用全部 Token")
        return

    if action == "delete_all":
        await config_registry.delete_all_pixiv_tokens()
        await _reload_pixiv_service()
        updated_tokens = await config_registry.get_pixiv_tokens()
        await context.bot.edit_message_reply_markup(
            chat_id=chat.id,
            message_id=panel_message_id,
            reply_markup=_build_main_menu(updated_tokens),
        )
        await refresh_bot_config_panel(context, chat_id=chat.id, message_id=panel_message_id)
        await query.answer("已清除全部 Token")
        return

    await query.answer()
