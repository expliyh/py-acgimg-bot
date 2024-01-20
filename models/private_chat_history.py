from sqlalchemy import Column, Integer, String, Boolean, Enum, DateTime, Text, JSON

from configs import config as file_config
from defines import MessageType

from .base import Base


class PrivateChatHistory(Base):
    __tablename__ = f"{file_config.db_prefix}private_chat_history"
    message_id = Column(Integer, primary_key=True, comment='消息的 ID')
    user_id = Column(Integer, primary_key=True, nullable=False, comment='用户的 ID')
    type = Column(Enum(MessageType), default=MessageType.TEXT, index=True, nullable=False, comment='消息的类型')
    bot_send = Column(Boolean, default=False, nullable=False, comment='是否为机器人发送的消息')
    file_id = Column(String(128), nullable=True, comment='消息的文件 ID')
    text = Column(Text, nullable=True, comment='消息的文本')
    key_board: list = Column(JSON, nullable=True, comment='消息的键盘')
    sent_at = Column(DateTime, nullable=False, comment='消息的发送时间')
