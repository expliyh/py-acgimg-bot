from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from handlers.registry import bot_handler
from services.command_history import command_logger
from services.manual_illustration_importer import import_manual_illustration
from services.permissions import has_super_user_access

logger = logging.getLogger(__name__)


def _parse_options(args: list[str]) -> tuple[str, dict[str, object]]:
    values: dict[str, str] = {}
    title_parts: list[str] = []
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            values[key.lower().strip()] = value.strip()
        else:
            title_parts.append(arg)
    title = values.pop("name", values.pop("title", " ".join(title_parts))).strip()
    truthy = {"1", "true", "yes", "on", "是"}
    options: dict[str, object] = {
        "author_name": values.get("author"),
        "source_url": values.get("source"),
        "author_url": values.get("author_url"),
        "caption": values.get("caption"),
        "tags": [tag.strip() for tag in values.get("tags", "").split(",") if tag.strip()],
        "is_ai": values.get("ai", "").lower() in truthy,
        "is_r18": values.get("r18", "").lower() in truthy,
        "is_r18g": values.get("r18g", "").lower() in truthy,
    }
    return title, options


@bot_handler(commands=["addimage"])
@command_logger("addimage")
async def add_manual_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user_id = update.effective_user.id if update.effective_user else None
    if not await has_super_user_access(user_id):
        await message.reply_text("您没有权限使用此命令。")
        return

    media_message = message.reply_to_message or message
    telegram_file = None
    filename = "image.jpg"
    if media_message.photo:
        telegram_file = await media_message.photo[-1].get_file()
    elif media_message.document and (media_message.document.mime_type or "").startswith("image/"):
        telegram_file = await media_message.document.get_file()
        filename = media_message.document.file_name or filename
    if telegram_file is None:
        await message.reply_text(
            "请回复一张图片并发送：\n"
            "/addimage 名称 author=作者 source=来源链接 author_url=作者链接 "
            "ai=yes r18=yes r18g=no tags=标签1,标签2\n"
            "除名称外的字段均可省略。"
        )
        return

    title, options = _parse_options(list(context.args or []))
    if not title:
        await message.reply_text("请提供图片名称，例如：/addimage 我的图片")
        return
    status = await message.reply_text("正在保存图片，请稍候…")
    try:
        data = bytes(await telegram_file.download_as_bytearray())
        result = await import_manual_illustration(data, filename=filename, title=title, **options)
    except Exception as exc:  # pragma: no cover - Telegram/storage interaction
        logger.exception("Failed to import manually submitted image")
        await status.edit_text(f"添加失败：{exc}")
        return
    await status.edit_text(f"图片“{result.illustration.title}”已添加（ID: {result.illustration.id}）。")
