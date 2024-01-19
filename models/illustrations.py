from sqlalchemy import Column, Integer, String, Boolean, Enum, JSON, Text

from .base import ModelBase


class Illustration(ModelBase):
    __tablename__ = 'illustrations'
    id = Column(String(20), primary_key=True, comment='插画的 PixivID')
    title = Column(String(64), nullable=True, comment='插画的标题')
    author_id = Column(String(20), nullable=False, comment='插画的作者 ID')
    author_name = Column(String(64), nullable=True, comment='插画的作者名')
    page_count = Column(Integer, nullable=False, comment='插画的页数')
    sanity_level = Column(Integer, nullable=False, comment='插画的过滤等级')
    r18g = Column(Boolean, default=False, nullable=False, comment='是否为 R18G 插画')
    x_restrict = Column(Integer, nullable=False, comment='插画的限制级')
    tags: list = Column(JSON, default=[], nullable=False, comment='插画的标签')
    caption = Column(Text, nullable=True, comment='插画的描述')
    is_ai = Column(Boolean, default=False, nullable=False, comment='是否为 AI 插画')
    file_urls: list = Column(JSON, default=[], nullable=False, comment='插画的文件链接')
    origin_urls: list = Column(JSON, default=[], nullable=False, comment='插画的原始链接')
