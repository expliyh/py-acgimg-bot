from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func

from configs import config as file_config

from .base import Base


class CommandHistory(Base):
    __tablename__ = f"{file_config.db_prefix}command_history"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="记录 ID")
    command = Column(String(64), nullable=False, index=True, comment="执行的命令名称")
    user_id = Column(BigInteger, nullable=True, index=True, comment="触发命令的用户 ID")
    chat_id = Column(BigInteger, nullable=True, index=True, comment="命令所在的会话 ID")
    chat_type = Column(String(32), nullable=True, comment="会话类型，如 private 或 supergroup")
    message_id = Column(BigInteger, nullable=True, comment="命令关联的消息 ID")
    arguments = Column(JSON, nullable=True, comment="命令参数列表")
    raw_text = Column(Text, nullable=True, comment="命令的原始文本内容")
    success = Column(Boolean, nullable=False, default=True, comment="命令是否执行成功")
    error_message = Column(Text, nullable=True, comment="命令执行失败时的错误信息")
    duration_ms = Column(Integer, nullable=True, comment="命令处理耗时，单位毫秒")
    triggered_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="命令触发的时间",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"<CommandHistory id={self.id} command={self.command!r} user_id={self.user_id} "
            f"chat_id={self.chat_id} success={self.success}>"
        )
