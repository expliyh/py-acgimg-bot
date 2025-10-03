from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from services.permissions import has_super_user_access
from services import pixiv
from services.command_history import command_logger
from services.illustration_importer import import_illustration
from handlers.registry import bot_handler

logger = logging.getLogger(__name__)


def _build_chat_candidates(update: Update) -> list[int]:
    candidates: list[int] = []
    if update.effective_user is not None:
        candidates.append(update.effective_user.id)
    if update.effective_chat is not None and update.effective_chat.id not in candidates:
        candidates.append(update.effective_chat.id)
    return candidates


def _format_page_summary(index: int, *, storage: bool, photo: bool, document: bool) -> str:
    return (
        f" - 第 {index + 1} 页："
        f"存储{'成功' if storage else '失败'}，"
        f"PhotoID{'已缓存' if photo else '缺失'}，"
        f"DocumentID{'已缓存' if document else '缺失'}"
    )


@bot_handler(commands=["addpixiv"])
@command_logger("addpixiv")
async def add_pixiv_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not pixiv.enabled:
        await update.effective_message.reply_text(
            "Pixiv 功能未启用，请联系管理员配置令牌。"
        )
        return

    args = context.args or []
    if not args:
        await update.effective_message.reply_text("请提供要导入的 Pixiv ID，例如 /addpixiv 12345678。")
        return

    pixiv_id_raw = args[0].strip()
    try:
        pixiv_id = int(pixiv_id_raw)
    except ValueError:
        await update.effective_message.reply_text("Pixiv ID 必须是数字。")
        return

    user_id = update.effective_user.id if update.effective_user else None
    if not await has_super_user_access(user_id):
        await update.effective_message.reply_text("您没有权限使用此命令。")
        return

    status_message = await update.effective_message.reply_text("正在导入插画，请稍候……")
    chat_candidates = _build_chat_candidates(update)

    try:
        result = await import_illustration(
            pixiv_id,
            bot=context.bot,
            telegram_chat_ids=chat_candidates,
        )
    except Exception as exc:  # pragma: no cover - network interaction
        logger.exception("Failed to import Pixiv illustration %s", pixiv_id)
        await status_message.edit_text(f"导入失败：{exc}")
        return

    illustration = result.illustration
    header = (
        f"插画 {illustration.title or illustration.id} (Pixiv {illustration.id}) "
        f"已{'新增' if result.created else '更新'}。"
    )
    summary_lines = [header, f"共处理 {len(result.pages)} 张图片。"]
    for page in result.pages:
        summary_lines.append(
            _format_page_summary(
                page.index,
                storage=bool(page.storage_url),
                photo=bool(page.compressed_file_id),
                document=bool(page.original_file_id),
            )
        )

    await status_message.edit_text("\n".join(summary_lines))
