import os
from collections.abc import Iterable

from sqlalchemy import Column, Integer, String, Boolean, Enum, JSON, Text

from configs import config as file_config

from .base import Base


class Illustration(Base):
    __tablename__ = f"{file_config.db_prefix}illustrations"
    id = Column(String(20), primary_key=True, comment='插画的 PixivID')
    title = Column(String(64), nullable=True, comment='插画的标题')
    author_id = Column(String(20), nullable=False, comment='插画的作者 ID')
    author_name = Column(String(64), nullable=True, comment='插画的作者名')
    page_count = Column(Integer, nullable=False, comment='插画的页数')
    sanity_level = Column(Integer, index=True, nullable=False, comment='插画的过滤等级')
    r18g = Column(Boolean, default=False, index=True, nullable=False, comment='是否为 R18G 插画')
    x_restrict = Column(Integer, index=True, nullable=False, comment='插画的限制级')
    tags: list = Column(JSON, default=[], nullable=False, comment='插画的标签')
    caption = Column(Text, nullable=True, comment='插画的描述')
    is_ai = Column(Boolean, default=False, nullable=False, comment='是否为 AI 插画')
    file_urls: list = Column(JSON, default=[], nullable=False, comment='插画的文件链接')
    compressed_file_ids: [str | None] = Column(JSON, default=[], nullable=False, comment='插画的压缩文件 ID')
    original_file_ids: [str | None] = Column(JSON, default=[], nullable=False, comment='插画的原始文件 ID')
    origin_urls: list = Column(JSON, default=[], nullable=False, comment='插画的原始链接')
    file_ext: [str] = Column(JSON, default=[], nullable=False, comment='插画的文件后缀')

    def get_markdown(self) -> str:
        if self.page_count == 1:
            return \
                f"**{self.title}**\n\n" \
                f"作者: [{self.author_name}](https://www.pixiv.net/users/{self.author_id})\n\n" \
                f"描述: {self.caption}\n\n" \
                f"[原图]({self.origin_urls[0]})\n\n" \
                f"AI: {'是' if self.is_ai else '否'}"

        else:
            return \
                f"**{self.title}**\n\n" \
                f"作者: [{self.author_name}](https://www.pixiv.net/users/{self.author_id})\n\n" \
                f"描述: {self.caption}\n\n" \
                f"原图: {', '.join([f'[{i + 1}]({self.origin_urls[i]})' for i in range(self.page_count)])}\n\n" \
                f"AI: {'是' if self.is_ai else '否'}"


def build_illust_from_api_dict(api_dict: dict) -> Illustration:
    raw_tags = api_dict.get('tags', [])
    tags: list[str] = []
    if isinstance(raw_tags, str):
        cleaned = raw_tags.strip()
        if cleaned:
            tags.append(cleaned)
    elif isinstance(raw_tags, Iterable):
        for tag in raw_tags:
            if isinstance(tag, dict):
                name = tag.get('name')
                if name:
                    tags.append(str(name))
            elif isinstance(tag, str):
                cleaned = tag.strip()
                if cleaned:
                    tags.append(cleaned)

    page_count = int(api_dict['page_count'])

    illust = Illustration(
        id=str(api_dict['id']),
        title=api_dict['title'],
        author_id=str(api_dict['user']['id']),
        author_name=api_dict['user']['name'],
        page_count=page_count,
        sanity_level=int(api_dict['sanity_level']),
        r18g=int(api_dict['x_restrict']) >= 2,
        x_restrict=api_dict['x_restrict'],
        tags=tags,
        caption=api_dict['caption'],
        is_ai=int(api_dict['illust_ai_type']) == 2,
        file_urls=[],
        compressed_file_ids=[],
        original_file_ids=[],
        origin_urls=[],
        file_ext=[]
    )
    origin_urls: list[str] = []
    file_exts: list[str] = []

    def _append(origin_url: str | None) -> None:
        if not origin_url:
            raise RuntimeError("Pixiv API 响应缺少原图链接")
        origin_urls.append(origin_url)
        ext = os.path.splitext(origin_url)[1] or ".jpg"
        if not ext.startswith("."):
            ext = f".{ext}"
        file_exts.append(ext)

    if illust.page_count == 1:
        single_page = api_dict.get('meta_single_page', {})
        _append(single_page.get('original_image_url'))
    else:
        meta_pages: Iterable[dict] = api_dict.get('meta_pages', [])
        for page in meta_pages:
            image_urls = page.get('image_urls') if isinstance(page, dict) else None
            origin_url = image_urls.get('original') if isinstance(image_urls, dict) else None
            _append(origin_url)

    if len(origin_urls) != illust.page_count:
        raise RuntimeError("插画页数与返回的原图数量不一致")

    illust.origin_urls = origin_urls
    illust.file_ext = file_exts
    illust.file_urls = [None] * illust.page_count
    illust.compressed_file_ids = [None] * illust.page_count
    illust.original_file_ids = [None] * illust.page_count
    return illust
