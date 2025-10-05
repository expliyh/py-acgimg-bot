from __future__ import annotations

import logging
from io import BytesIO
from typing import Sequence

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from defines import GroupStatus, UserStatus
from exps import UserBlockedError, GroupBlockedError

from utils import is_group_type, ensure_list_length

from registries import user_registry, group_registry, illust_registry
from services.command_history import command_logger
from services.image_service import ImageResource, get_image_resource
from services.original_image_manager import (
    OriginalImageRequest,
    create_request,
    register_request,
)
from handlers.registry import bot_handler

logger = logging.getLogger(__name__)


def _parse_pixiv_arguments(args: Sequence[str]) -> tuple[int | None, str | None]:
    for raw in args:
        value = raw.strip()
        if not value:
            continue
        key, sep, rest = value.partition("=")
        if sep:
            if key.lower() not in {"id", "pixiv", "pid"}:
                continue
            candidate = rest.strip()
            if not candidate:
                return None, raw
        else:
            if not value.isdigit():
                continue
            candidate = value
        if not candidate.isdigit():
            return None, raw
        try:
            return int(candidate), None
        except ValueError:
            return None, raw
    return None, None


async def _reply_with_text(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None,
) -> None:
    send_kwargs = {"chat_id": chat_id, "text": text}
    if reply_to_message_id is not None:
        send_kwargs["reply_to_message_id"] = reply_to_message_id
    await context.bot.send_message(**send_kwargs)


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

    args = tuple(getattr(context, "args", ()) or ())
    pixiv_id, parse_error = _parse_pixiv_arguments(args)
    reply_to_id = message.id if message else None
    if parse_error:
        await _reply_with_text(
            context,
            chat_id=chat_id,
            text=f"ID 参数格式不正确：{parse_error}",
            reply_to_message_id=reply_to_id,
        )
        return

    if pixiv_id is not None:
        illust_info = await illust_registry.get_illust_info(pixiv_id)
        if illust_info is None:
            await _reply_with_text(
                context,
                chat_id=chat_id,
                text="未找到指定 ID 的图片，请先添加到数据库。",
                reply_to_message_id=reply_to_id,
            )
            return
        if illust_info.sanity_level > sanity_limit:
            await _reply_with_text(
                context,
                chat_id=chat_id,
                text="指定的图片过滤等级超过当前限制，无法发送。",
                reply_to_message_id=reply_to_id,
            )
            return
        if illust_info.r18g and not allow_r18g:
            await _reply_with_text(
                context,
                chat_id=chat_id,
                text="指定的图片包含 R18G 内容，当前设置不允许发送。",
                reply_to_message_id=reply_to_id,
            )
            return

    try:
        resource: ImageResource = await get_image_resource(
            pixiv_id=pixiv_id,
            sanity_limit=sanity_limit,
            allow_r18g=allow_r18g,
        )
    except FileNotFoundError:
        if pixiv_id is not None:
            await _reply_with_text(
                context,
                chat_id=chat_id,
                text="未能获取到指定 ID 的图片资源，请稍后再试。",
                reply_to_message_id=reply_to_id,
            )
            return
        raise

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

    image_file = BytesIO(await resource.fetcher(resource.file_id, resource.link))
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
