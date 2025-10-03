from __future__ import annotations

import logging
from io import BytesIO

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from defines import GroupStatus, UserStatus
from exps import UserBlockedError, GroupBlockedError

from utils import is_group_type, ensure_list_length

from registries import user_registry, group_registry, illust_registry
from services.command_history import command_logger
from services.image_service import ImageResource, get_image
from services.original_image_manager import (
    OriginalImageRequest,
    create_request,
    register_request,
)
from handlers.registry import bot_handler


logger = logging.getLogger(__name__)


@bot_handler
@command_logger("setu")
async def setu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await user_registry.get_user_by_id(update.effective_user.id)
    if user.status == UserStatus.BLOCKED:
        raise UserBlockedError("您已被禁止使用本Bot")
    if user.status == UserStatus.INACTIVE:
        raise UserBlockedError("您未启用本Bot, 请先到设置中启用")

    chat = update.effective_chat
    message = update.effective_message
    chat_id = chat.id
    is_group = is_group_type(chat.type)

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

    resource: ImageResource = await get_image(
        sanity_limit=sanity_limit,
        allow_r18g=allow_r18g,
    )

    illust = resource.illustration
    caption_lines = [
        f"标题: {illust.title}",
        f"作者: {illust.author_name} (Pixiv {illust.author_id})",
        f"页码: {resource.page_id + 1}/{illust.page_count}",
        f"AI 作品: {'是' if illust.is_ai else '否'}",
    ]

    request_state: OriginalImageRequest | None = None
    try:
        pixiv_id = int(str(illust.id))
    except (TypeError, ValueError):
        logger.warning("Unexpected illustration id %r, original image button disabled", illust.id)
    else:
        request_state = create_request(
            chat_id=chat_id,
            user_id=user.id,
            pixiv_id=pixiv_id,
            page_id=resource.page_id,
        )

    send_kwargs = {
        "chat_id": chat_id,
        "caption": "\n".join(caption_lines),
    }
    if message is not None:
        send_kwargs["reply_to_message_id"] = message.id
    if request_state is not None:
        send_kwargs["reply_markup"] = request_state.build_markup()

    sent_message = None
    if resource.file_id:
        try:
            sent_message = await context.bot.send_photo(photo=resource.file_id, **send_kwargs)
        except TelegramError as exc:
            logger.warning("Failed to reuse cached photo %s: %s", resource.file_id, exc)
            ids = ensure_list_length(getattr(illust, "compressed_file_ids", None), illust.page_count)
            if ids[resource.page_id] == resource.file_id:
                ids[resource.page_id] = None
                illust.compressed_file_ids = ids
                await illust_registry.save_illustration(illust)
        else:
            if request_state is not None:
                request_state.message_id = sent_message.id
                await register_request(context.bot, request_state)
            return

    image_file = BytesIO(resource.image_bytes)
    image_file.name = resource.filename
    sent_message = await context.bot.send_photo(photo=image_file, **send_kwargs)

    if request_state is not None:
        request_state.message_id = sent_message.id
        await register_request(context.bot, request_state)

    photo_sizes = sent_message.photo or []
    if not photo_sizes:
        return

    cached_id = photo_sizes[-1].file_id
    if not cached_id:
        return

    ids = ensure_list_length(getattr(illust, "compressed_file_ids", None), illust.page_count)
    if ids[resource.page_id] == cached_id:
        return

    ids[resource.page_id] = cached_id
    illust.compressed_file_ids = ids
    await illust_registry.save_illustration(illust)
