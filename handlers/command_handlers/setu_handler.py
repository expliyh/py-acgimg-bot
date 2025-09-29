from io import BytesIO

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from defines import GroupStatus, UserStatus
from exps import UserBlockedError, GroupBlockedError

from utils import is_group_type

from registries import user_registry, group_registry
from services.image_service import get_image


async def setu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await user_registry.get_user_by_id(update.effective_user.id)
    if user.status == UserStatus.BLOCKED:
        raise UserBlockedError("您已被禁止使用本Bot")
    if user.status == UserStatus.INACTIVE:
        raise UserBlockedError("您未启用本Bot, 请先到设置中启用。")
    chat_id = update.effective_chat.id
    is_group = is_group_type(update.effective_chat.type)
    group = None
    if is_group:
        group = await group_registry.get_group_by_id(chat_id)
        if group.status == GroupStatus.BLOCKED:
            raise GroupBlockedError("本群组已被禁止使用本Bot")
        if not group.enable or group.status == GroupStatus.DISABLED:
            raise GroupBlockedError("本群组暂未启用本Bot")
        if not group.allow_setu:
            raise GroupBlockedError("本群组已关闭涩图功能")

    sanity_limit = user.sanity_limit
    allow_r18g = user.allow_r18g
    if is_group and group is not None:
        sanity_limit = min(sanity_limit, group.sanity_limit)
        allow_r18g = allow_r18g and group.allow_r18g

    illust, image_bytes, page_id, filename = await get_image(
        sanity_limit=sanity_limit,
        allow_r18g=allow_r18g,
    )

    image_file = BytesIO(image_bytes)
    image_file.name = filename

    caption_lines = [
        f"标题: {illust.title}",
        f"作者: {illust.author_name} (Pixiv {illust.author_id})",
        f"页码: {page_id + 1}/{illust.page_count}",
        f"AI 作品: {'是' if illust.is_ai else '否'}",
    ]

    origin_urls = illust.origin_urls or []
    if isinstance(origin_urls, list):
        if page_id < len(origin_urls) and origin_urls[page_id]:
            caption_lines.append(f"原图: {origin_urls[page_id]}")
    elif isinstance(origin_urls, str) and origin_urls:
        caption_lines.append(f"原图: {origin_urls}")

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=image_file,
        caption="\n".join(caption_lines),
        reply_to_message_id=update.effective_message.id,
    )


setu_handler = CommandHandler("setu", setu)
