from sqlalchemy import BigInteger, Column, ForeignKey, String, Index

from configs import config as file_config
from .base import Base


class ActiveMessageHandler(Base):
    __tablename__ = f"{file_config.db_prefix}active_message_handler"

    group_id = Column(BigInteger, index=True, primary_key=True)  # 为 `group_id` 添加单列索引
    user_id = Column(BigInteger, index=True, primary_key=True)  # 为 `user_id` 添加单列索引
    handler_id = Column(String(128))

    # 添加复合索引
    __table_args__ = (
        Index('idx_group_user', "group_id", "user_id"),
    )
