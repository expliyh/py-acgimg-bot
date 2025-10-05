from __future__ import annotations

import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Sequence

from telegram import Bot
from telegram.error import TelegramError

from models import Illustration
from registries import config_registry, illust_registry
from services.file_service import get_file
from services.pixiv_service import pixiv
from services.storage_service import use as use_storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImportedPage:
    index: int
    storage_url: str
    compressed_file_id: str | None
    original_file_id: str | None


@dataclass(slots=True)
class IllustrationImportResult:
    illustration: Illustration
    created: bool
    telegram_cache_enabled: bool = True
    pages: list[ImportedPage] = field(default_factory=list)


def _unique_chat_ids(chat_ids: Sequence[int] | None) -> list[int]:
    if not chat_ids:
        return []
    seen: set[int] = set()
    ordered: list[int] = []
    for chat_id in chat_ids:
        if chat_id in seen:
            continue
        seen.add(chat_id)
        ordered.append(chat_id)
    return ordered


async def _cache_photo_file_id(
    bot: Bot,
    chat_ids: list[int],
    data: bytes,
    filename: str,
    *,
    cleanup: bool,
) -> tuple[str | None, int | None]:
    last_error: Exception | None = None
    for chat_id in chat_ids:
        try:
            stream = BytesIO(data)
            stream.name = filename
            message = await bot.send_photo(
                chat_id=chat_id,
                photo=stream,
                disable_notification=True,
            )
        except TelegramError as exc:  # pragma: no cover - network interaction
            last_error = exc
            logger.debug("Failed to cache photo file id in chat %s: %s", chat_id, exc)
            continue
        compressed_id = message.photo[-1].file_id if message.photo else None
        if cleanup:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            except TelegramError as exc:  # pragma: no cover - best effort cleanup
                logger.debug("Failed to delete temporary photo message: %s", exc)
        return compressed_id, chat_id
    if last_error is not None:
        logger.warning("无法缓存压缩文件 ID: %s", last_error)
    return None, None


async def _cache_document_file_id(
    bot: Bot,
    chat_ids: list[int],
    data: bytes,
    filename: str,
    *,
    cleanup: bool,
) -> str | None:
    last_error: Exception | None = None
    for chat_id in chat_ids:
        try:
            stream = BytesIO(data)
            stream.name = filename
            message = await bot.send_document(
                chat_id=chat_id,
                document=stream,
                disable_notification=True,
            )
        except TelegramError as exc:  # pragma: no cover - network interaction
            last_error = exc
            logger.debug("Failed to cache document file id in chat %s: %s", chat_id, exc)
            continue
        file_id = message.document.file_id if message.document else None
        if cleanup:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            except TelegramError as exc:  # pragma: no cover - best effort cleanup
                logger.debug("Failed to delete temporary document message: %s", exc)
        return file_id
    if last_error is not None:
        logger.warning("无法缓存原图文件 ID: %s", last_error)
    return None


def _ensure_list(container: object, length: int) -> list:
    if isinstance(container, list):
        if len(container) < length:
            container.extend([None] * (length - len(container)))
        return container
    return [None] * length


def _resolve_bool(value: str | bool | None, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default


async def import_illustration(
    pixiv_id: int,
    *,
    bot: Bot | None = None,
    telegram_chat_ids: Sequence[int] | None = None,
    cleanup_messages: bool = True,
) -> IllustrationImportResult:
    if not pixiv.enabled:
        raise RuntimeError("Pixiv 功能未启用")

    illust = await pixiv.get_illust_info_by_pixiv_id(pixiv_id)
    storage = await use_storage()
    if storage is None:
        raise RuntimeError("未配置存储服务，请先在后台完成配置。")

    storage_folder = storage.join_path("pixiv", str(illust.id))
    existing = await illust_registry.get_illust_info(str(illust.id))
    created = existing is None

    cache_config_raw = await config_registry.get_config("pixiv_cache_to_telegram")
    telegram_cache_enabled = _resolve_bool(cache_config_raw, default=True)

    existing_compressed_ids = _ensure_list(
        existing.compressed_file_ids if existing else None,
        illust.page_count,
    )
    existing_original_ids = _ensure_list(
        existing.original_file_ids if existing else None,
        illust.page_count,
    )

    chat_candidates = _unique_chat_ids(telegram_chat_ids)

    illust.file_urls = _ensure_list(getattr(illust, "file_urls", None), illust.page_count)
    illust.compressed_file_ids = _ensure_list(getattr(illust, "compressed_file_ids", None), illust.page_count)
    illust.original_file_ids = _ensure_list(getattr(illust, "original_file_ids", None), illust.page_count)

    pages: list[ImportedPage] = []
    for page_index in range(illust.page_count):
        origin_url: str | None = None
        if isinstance(illust.origin_urls, list):
            if page_index < len(illust.origin_urls):
                origin_url = illust.origin_urls[page_index]
        elif isinstance(illust.origin_urls, str):
            origin_url = illust.origin_urls
        if not origin_url:
            raise RuntimeError(f"缺少第{page_index + 1} 页的原图链接")

        ext: str | None = None
        if isinstance(illust.file_ext, list):
            if page_index < len(illust.file_ext):
                ext = illust.file_ext[page_index]
        elif isinstance(illust.file_ext, str):
            ext = illust.file_ext
        if not ext:
            ext = ".jpg"
        if not ext.startswith("."):
            ext = f".{ext}"

        filename = f"{illust.id}_{page_index:02d}{ext}"
        file_bytes = await get_file(filename=filename, url=origin_url)
        if file_bytes is None:
            raise RuntimeError(f"无法下载第{page_index + 1} 页的图片")

        storage_url = await storage.upload(
            file_bytes,
            filename,
            sub_folder=storage_folder,
        )

        compressed_id: str | None = None
        original_id: str | None = None
        if bot is not None and chat_candidates and telegram_cache_enabled:
            compressed_id, used_chat = await _cache_photo_file_id(
                bot,
                chat_candidates,
                file_bytes,
                filename,
                cleanup=cleanup_messages,
            )
            doc_chat_order = chat_candidates
            if used_chat is not None:
                doc_chat_order = [used_chat] + [cid for cid in chat_candidates if cid != used_chat]
            original_id = await _cache_document_file_id(
                bot,
                doc_chat_order,
                file_bytes,
                filename,
                cleanup=cleanup_messages,
            )
        elif not telegram_cache_enabled:
            compressed_id = existing_compressed_ids[page_index]
            original_id = existing_original_ids[page_index]

        illust.file_urls[page_index] = storage_url
        illust.compressed_file_ids[page_index] = compressed_id
        illust.original_file_ids[page_index] = original_id

        pages.append(
            ImportedPage(
                index=page_index,
                storage_url=storage_url,
                compressed_file_id=compressed_id,
                original_file_id=original_id,
            )
        )

    saved = await illust_registry.save_illustration(illust)
    saved.file_urls = illust.file_urls
    saved.compressed_file_ids = illust.compressed_file_ids
    saved.original_file_ids = illust.original_file_ids

    return IllustrationImportResult(
        illustration=saved,
        created=created,
        telegram_cache_enabled=telegram_cache_enabled,
        pages=pages,
    )



