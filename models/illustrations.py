import os

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
                f"**{self.title}**\n" \
                f"作者: [{self.author_name}](https://www.pixiv.net/users/{self.author_id})\n" \
                f"描述: {self.caption}\n" \
                f"[原图]({self.origin_urls[0]})" \
                f"AI: {'是' if self.is_ai else '否'}\n"

        else:
            return \
                f"**{self.title}**\n" \
                f"作者: [{self.author_name}](https://www.pixiv.net/users/{self.author_id})\n" \
                f"描述: {self.caption}\n" \
                f"原图: {', '.join([f'[{i + 1}]({self.origin_urls[i]})' for i in range(self.page_count)])}" \
                f"AI: {'是' if self.is_ai else '否'}\n"


def build_illust_from_api_dict(api_dict: dict) -> Illustration:
    illust = Illustration(
        id=str(api_dict['id']),
        title=api_dict['title'],
        author_id=str(api_dict['user']['id']),
        author_name=api_dict['user']['name'],
        page_count=api_dict['page_count'],
        sanity_level=int(api_dict['sanity_level']),
        r18g=int(api_dict['x_restrict']) >= 2,
        x_restrict=api_dict['x_restrict'],
        tags=api_dict['tags'],
        caption=api_dict['caption'],
        is_ai=int(api_dict['illust_ai_type']) == 2,
        file_urls=[],
        compressed_file_ids=[],
        original_file_ids=[],
        origin_urls=[],
        file_ext=[]
    )
    if illust.page_count == 1:
        illust.origin_urls = [api_dict['meta_single_page']['original_image_url']]
        illust.file_ext = os.path.splitext(api_dict['meta_single_page']['original_image_url'])[1]
    else:
        for i in range(illust.page_count):
            illust.origin_urls.append(api_dict['meta_pages'][i]['image_urls']['original'])
            illust.file_ext = os.path.splitext(api_dict['meta_pages'][i]['image_urls']['original'])[1]
    return illust
