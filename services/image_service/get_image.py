from __future__ import annotations

from dataclasses import dataclass
import os
import random

from models import Illustration

import registries
from services import file_service
from exps import BadRequestError


@dataclass(slots=True)
class ImageResource:
    illustration: Illustration
    page_id: int
    filename: str
    image_bytes: bytes
    file_id: str | None
    link: str
    is_original: bool


def _resolve_page_id(illust: Illustration, page_id: int | None, allow_random: bool) -> int:
    if illust.page_count is None or illust.page_count <= 0:
        raise FileNotFoundError("该作品没有可用的图片")
    if page_id is None:
        if allow_random:
            return random.randrange(illust.page_count)
        return 0
    if page_id < 0 or page_id >= illust.page_count:
        raise BadRequestError("请求的页码超出范围")
    return page_id


def _resolve_link(illust: Illustration, page_id: int) -> str:
    file_urls = illust.file_urls or []
    origin_urls = illust.origin_urls or []

    if isinstance(file_urls, list):
        if page_id < len(file_urls) and file_urls[page_id]:
            return file_urls[page_id]
    elif isinstance(file_urls, str) and file_urls:
        return file_urls

    if isinstance(origin_urls, list):
        if page_id < len(origin_urls) and origin_urls[page_id]:
            return origin_urls[page_id]
    elif isinstance(origin_urls, str) and origin_urls:
        return origin_urls

    raise FileNotFoundError("没有找到对应页面的图片链接")


def _resolve_extension(illust: Illustration, page_id: int, link: str) -> str:
    file_ext = illust.file_ext
    ext: str | None = None

    if isinstance(file_ext, list):
        if page_id < len(file_ext):
            candidate = file_ext[page_id]
            if isinstance(candidate, str):
                ext = candidate
    elif isinstance(file_ext, tuple):
        if len(file_ext) > 1 and isinstance(file_ext[1], str):
            ext = file_ext[1]
    elif isinstance(file_ext, str):
        ext = file_ext

    if not ext:
        ext = os.path.splitext(link)[1]

    if not ext:
        ext = ".jpg"
    elif not ext.startswith("."):
        ext = f".{ext}"

    return ext


def _resolve_file_id(illust: Illustration, page_id: int, *, origin: bool) -> str | None:
    container = getattr(illust, "original_file_ids" if origin else "compressed_file_ids", None)
    if isinstance(container, list):
        if page_id < len(container):
            value = container[page_id]
            if isinstance(value, str):
                cleaned = value.strip()
                return cleaned or None
        return None
    if isinstance(container, (tuple, set)):
        try:
            value = list(container)[page_id]
        except (IndexError, TypeError):
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return None
    if isinstance(container, str):
        cleaned = container.strip()
        return cleaned or None
    return None


async def get_image(
    pixiv_id: int | None = None,
    page_id: int | None = None,
    origin: bool = False,
    sanity_limit: int = 5,
    allow_r18g: bool = False,
) -> ImageResource:
    if pixiv_id is not None:
        illust = await registries.get_illust_info(pixiv_id)
        if illust is None:
            raise FileNotFoundError(f"No such illust in database: {pixiv_id}")
        resolved_page_id = _resolve_page_id(illust, page_id, allow_random=False)
        link = _resolve_link(illust, resolved_page_id)
        ext = _resolve_extension(illust, resolved_page_id, link)
        filename = f"{illust.id}_{resolved_page_id}{ext}"
        fetcher = file_service.get_file if origin else file_service.get_image
        image = await fetcher(filename=filename, url=link)
        if image is None:
            raise FileNotFoundError("未能获取到图片文件")
        file_id = _resolve_file_id(illust, resolved_page_id, origin=origin)
        return ImageResource(
            illustration=illust,
            page_id=resolved_page_id,
            filename=filename,
            image_bytes=image,
            file_id=file_id,
            link=link,
            is_original=origin,
        )

    if origin:
        raise BadRequestError("随机图片不可请求原图")

    illust = await registries.random_illust(sanity_limit=sanity_limit, r18g=allow_r18g)
    if illust is None:
        raise FileNotFoundError("数据库中没有符合条件的插画")

    resolved_page_id = _resolve_page_id(illust, page_id, allow_random=True)
    link = _resolve_link(illust, resolved_page_id)
    ext = _resolve_extension(illust, resolved_page_id, link)
    filename = f"{illust.id}_{resolved_page_id}{ext}"
    image = await file_service.get_image(filename=filename, url=link)
    if image is None:
        raise FileNotFoundError("未能获取到图片文件")

    file_id = _resolve_file_id(illust, resolved_page_id, origin=False)

    return ImageResource(
        illustration=illust,
        page_id=resolved_page_id,
        filename=filename,
        image_bytes=image,
        file_id=file_id,
        link=link,
        is_original=False,
    )
