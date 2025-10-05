from __future__ import annotations

import logging
from io import BytesIO

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from registries import illust_registry
from services.image_service import ImageResource, get_image_resource
from services.original_image_manager import (
    MAX_ATTEMPTS,
    get_request,
    is_request_active,
    update_markup,
)
from utils import ensure_list_length

logger = logging.getLogger(__name__)


async def callback_original_image_handler(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        args: list[str],
) -> None:
    query = update.callback_query
    if query is None:
        return
    if not args:
        await query.answer("请求无效", show_alert=True)
        return

    token = args[0]
    state = await get_request(token)
    if state is None:
        await query.answer("请求已过期", show_alert=True)
        return

    if query.message is None or query.message.id != state.message_id:
        await query.answer("请求已失效", show_alert=True)
        return

    if query.from_user.id != state.user_id:
        await query.answer("仅请求者可以获取原图", show_alert=True)
        return

    if not await is_request_active(state):
        await query.answer("请求已过期", show_alert=True)
        return

    async with state.lock:
        if state.status == "fetching":
            await query.answer("原图获取中，请稍后", show_alert=False)
            return
        if state.status == "success":
            await query.answer("已获取原图，请勿再次获取", show_alert=True)
            return
        if state.attempts >= MAX_ATTEMPTS:
            state.status = "exhausted"
            await update_markup(context.bot, state)
            await query.answer("重试次数已达上限", show_alert=True)
            return
        state.status = "fetching"
        await update_markup(context.bot, state)

    await query.answer("正在获取原图…", show_alert=False)

    try:
        resource = await get_image_resource(
            pixiv_id=state.pixiv_id,
            page_id=state.page_id,
            origin=True,
        )
        await _send_original_image(context.bot, resource, state.chat_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "Failed to send original image for %s (page %s): %s",
            state.pixiv_id,
            state.page_id,
            exc,
        )
        async with state.lock:
            state.attempts += 1
            if state.attempts >= MAX_ATTEMPTS:
                state.status = "exhausted"
            else:
                state.status = "ready"
            await update_markup(context.bot, state)
        message = (
            "原图获取失败，请稍后重试"
            if state.attempts < MAX_ATTEMPTS
            else "原图获取失败，请稍后再试"
        )
        await query.answer(message, show_alert=True)
        return

    async with state.lock:
        state.status = "success"
        await update_markup(context.bot, state)
    await query.answer("原图获取成功", show_alert=False)


async def _send_original_image(bot, resource: ImageResource, chat_id: int) -> None:
    illustration = resource.illustration
    page_id = resource.page_id

    if resource.file_id:
        try:
            await bot.send_document(chat_id=chat_id, document=resource.file_id)
        except TelegramError as exc:
            logger.warning(
                "Failed to reuse cached original file %s: %s",
                resource.file_id,
                exc,
            )
            await _clear_cached_original_id(illustration, page_id, resource.file_id)
        else:
            return

    document_file = BytesIO(await resource.fetcher(resource.filename, resource.link))
    document_file.name = resource.filename
    sent_message = await bot.send_document(chat_id=chat_id, document=document_file)

    document = sent_message.document
    if document and document.file_id:
        await _store_original_file_id(illustration, page_id, document.file_id)


async def _clear_cached_original_id(illustration, page_id: int, cached_id: str) -> None:
    ids = ensure_list_length(getattr(illustration, "original_file_ids", None), illustration.page_count)
    if ids[page_id] == cached_id:
        ids[page_id] = None
        illustration.original_file_ids = ids
        await illust_registry.save_illustration(illustration)


async def _store_original_file_id(illustration, page_id: int, file_id: str) -> None:
    ids = ensure_list_length(getattr(illustration, "original_file_ids", None), illustration.page_count)
    if ids[page_id] == file_id:
        return
    ids[page_id] = file_id
    illustration.original_file_ids = ids
    await illust_registry.save_illustration(illustration)
