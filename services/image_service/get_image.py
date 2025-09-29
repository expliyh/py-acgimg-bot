import os
import random

from models import Illustration

import registries
from services import file_service
from exps import BadRequestError


def _resolve_page_id(illust: Illustration, page_id: int | None, allow_random: bool) -> int:
    if illust.page_count is None or illust.page_count <= 0:
        raise FileNotFoundError("该作品没有可用的图片页")
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


async def get_image(
    pixiv_id: int | None = None,
    page_id: int | None = None,
    origin: bool = False,
    sanity_limit: int = 5,
    allow_r18g: bool = False,
) -> tuple[Illustration, bytes, int, str]:
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
        return illust, image, resolved_page_id, filename

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

    return illust, image, resolved_page_id, filename
