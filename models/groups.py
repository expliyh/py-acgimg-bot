from sqlalchemy import Column, BigInteger, Integer, String, Boolean, Enum, JSON

from defines import GroupChatMode, GroupStatus
from configs import config as file_config

from .base import Base


class Group(Base):
    __tablename__ = f"{file_config.db_prefix}groups"
    id = Column(BigInteger, primary_key=True, comment='群组的 ID')
    status = Column(Enum(GroupStatus), default=GroupStatus.ENABLED, nullable=False, comment='群组状态')
    enable = Column(Boolean, default=True, nullable=False, comment='是否启用此群组')
    name = Column(String(64), nullable=True, comment='群组的名称')
    enable_chat = Column(Boolean, default=False, nullable=False, comment='是否启用 AI 聊天')
    chat_mode = Column(Enum(GroupChatMode), default=GroupChatMode.MIXED, nullable=False, comment='群组的聊天模式')
    sanity_limit = Column(Integer, default=5, nullable=False, comment='群组允许的最大过滤等级 +1，该值为 7 则允许 R18')
    allow_r18g = Column(Boolean, default=False, nullable=False, comment='是否允许 R18G')
    allow_setu = Column(Boolean, default=True, nullable=False, comment='是否允许涩图')
    admin_ids: list = Column(JSON, default=[], nullable=False, comment='群组管理员的 ID')
