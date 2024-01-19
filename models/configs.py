from sqlalchemy import Column, String, Boolean

from .base import ModelBase


class Config(ModelBase):
    key: str = Column(String(64), primary_key=True, comment='配置的键')
    value_str: str = Column(String(64), nullable=True, comment='配置的值')
    value_bool: bool = Column(Boolean, nullable=True, comment='布尔型配置的值')
