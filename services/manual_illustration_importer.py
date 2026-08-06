from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from models import Illustration
from registries import illust_registry
from services.storage_service import use as use_storage


MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


@dataclass(slots=True)
class ManualImportResult:
    illustration: Illustration
    storage_url: str


def _validate_image_contents(data: bytes) -> None:
    """Reject malformed data and formats that the application cannot serve."""
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in ALLOWED_IMAGE_FORMATS:
                raise ValueError("仅支持 JPG、PNG、GIF 和 WebP 图片")
            image.verify()
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
    ) as exc:
        raise ValueError("图片文件已损坏或格式无效") from exc


async def import_manual_illustration(
    data: bytes,
    *,
    filename: str,
    title: str,
    author_name: str | None = None,
    source_url: str | None = None,
    author_url: str | None = None,
    caption: str | None = None,
    tags: list[str] | None = None,
    is_ai: bool = False,
    is_r18: bool = False,
    is_r18g: bool = False,
) -> ManualImportResult:
    if not data:
        raise ValueError("图片文件不能为空")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能超过 20 MB")
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("仅支持 JPG、PNG、GIF 和 WebP 图片")
    _validate_image_contents(data)
    title = title.strip()
    if not title:
        raise ValueError("名称不能为空")

    storage = await use_storage()
    if storage is None:
        raise RuntimeError("未配置存储服务，请先在后台完成配置。")

    illustration_id = f"manual_{uuid.uuid4().hex[:12]}"
    stored_name = f"{illustration_id}{ext}"
    storage_url = await storage.upload(
        data, stored_name, sub_folder=storage.join_path("manual", illustration_id)
    )
    illustration = Illustration(
        id=illustration_id,
        title=title,
        author_id="manual",
        author_name=(author_name or "").strip() or None,
        page_count=1,
        sanity_level=6 if is_r18 else 5,
        r18g=is_r18g,
        x_restrict=2 if is_r18g else (1 if is_r18 else 0),
        tags=tags or [],
        caption=(caption or "").strip() or None,
        is_ai=is_ai,
        file_urls=[storage_url],
        compressed_file_ids=[None],
        original_file_ids=[None],
        origin_urls=[],
        file_ext=[ext],
        source_type="manual",
        source_url=(source_url or "").strip() or None,
        author_url=(author_url or "").strip() or None,
    )
    saved = await illust_registry.save_illustration(illustration)
    return ManualImportResult(saved, storage_url)
