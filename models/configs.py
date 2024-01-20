from sqlalchemy import Column, String, Boolean

from configs import config as file_config

from .base import Base


class Config(Base):
    __tablename__ = f"{file_config.db_prefix}configs"
    key: str = Column(String(64), primary_key=True, comment='配置的键')
    value_str: str = Column(String(64), nullable=True, comment='配置的值')
    value_bool: bool = Column(Boolean, nullable=True, comment='布尔型配置的值')
