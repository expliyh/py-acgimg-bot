from sqlalchemy import Column, BigInteger, Integer, String, Boolean, Enum

from defines import UserStatus
from configs import config as file_config

from .base import Base


class User(Base):
    __tablename__ = f"{file_config.db_prefix}users"
    id = Column(BigInteger, primary_key=True, autoincrement=False, comment='用户的 UID，与 Telegram 的 UID 一致')
    nick_name = Column(String(64), nullable=True, comment='用户自定义的昵称，未设置则为空')
    enable_chat = Column(Boolean, default=False, nullable=False, comment='是否启用 AI 聊天')
    sanity_limit = Column(Integer, default=5, nullable=False, comment='用户允许的最大过滤等级 +1，该值为 7 则允许 R18')
    allow_r18g = Column(Boolean, default=False, nullable=False, comment='是否允许 R18G')
    status = Column(Enum(UserStatus), default=UserStatus.NORMAL, nullable=False, comment='用户状态')
