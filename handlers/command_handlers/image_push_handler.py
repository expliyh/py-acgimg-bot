"""Telegram command for an immediate image push to the current group."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from handlers.registry import bot_handler
from services.command_history import command_logger
from services.image_push import (
    _bot_can_send_photo,
    can_use_push_command,
    create_batch,
    group_push_block_reason,
    normalize_pid_spec,
)
from registries import group_registry
from utils import is_group_type


@bot_handler(commands="push")
@command_logger("push")
async def image_push_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message is None or chat is None:
        return
    if not is_group_type(chat.type):
        await message.reply_text("请在群组中使用 /push；跨群推送和自动计划请使用 Web 管理台。")
        return
    if not await can_use_push_command(user.id if user else None):
        await message.reply_text("您没有权限使用主动推送功能。")
        return

    group = await group_registry.get_group_by_id(chat.id)
    block_reason = group_push_block_reason(group)
    if block_reason:
        await message.reply_text(f"当前群无法发送图片：{block_reason}")
        return
    can_send, permission_reason = await _bot_can_send_photo(context.bot, chat.id)
    if not can_send:
        await message.reply_text(f"当前群无法发送图片：{permission_reason or '机器人没有发图权限'}")
        return

    args = [str(item).strip() for item in (context.args or []) if str(item).strip()]
    if len(args) > 1:
        await message.reply_text("用法：/push、/push random 或 /push PID[:页码]")
        return
    raw = args[0] if args else "random"
    if raw.lower() == "random":
        mode = "random_different"
        payload = {
            "target_scope": "selected",
            "group_ids": [chat.id],
            "mode": mode,
        }
    else:
        try:
            pid = normalize_pid_spec(raw)
        except ValueError as exc:
            await message.reply_text(str(exc))
            return
        payload = {
            "target_scope": "selected",
            "group_ids": [chat.id],
            "mode": "fixed_same",
            "pid": pid,
        }

    batch = await create_batch(payload, trigger="manual")
    await message.reply_text(f"图片推送已排队，批次 #{batch.id}；结果将在后台完成。")
