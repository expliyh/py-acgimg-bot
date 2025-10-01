from sqlalchemy import Boolean, Column, Integer, String

from configs import config as file_config

from .base import Base


class PixivToken(Base):
    __tablename__ = f"{file_config.db_prefix}pixiv_tokens"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="Pixiv Token ID")
    refresh_token = Column(String(512), nullable=False, comment="Pixiv Refresh Token")
    enabled = Column(Boolean, default=True, nullable=False, comment="Token enabled flag")
