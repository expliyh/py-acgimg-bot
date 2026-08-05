from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func

from configs import config as file_config

from .base import Base


class IllustrationImportTask(Base):
    __tablename__ = f"{file_config.db_prefix}illustration_import_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="任务 ID")
    pixiv_id = Column(String(20), nullable=False, index=True, comment="插画的 PixivID")
    title = Column(String(64), nullable=True, comment="插画的标题")
    status = Column(
        String(16), nullable=False, index=True, comment="任务状态: pending/running/success/failed"
    )
    created = Column(Boolean, nullable=True, comment="成功时是否为新增（False 为更新）")
    total_pages = Column(Integer, nullable=True, comment="总页数")
    current_page = Column(Integer, nullable=True, comment="当前处理到的页（1 起）")
    error_message = Column(Text, nullable=True, comment="失败时的错误信息")
    overrides = Column(JSON, nullable=True, comment="导入时用户覆盖的字段")
    result = Column(JSON, nullable=True, comment="成功时的导入结果摘要")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="任务创建时间",
    )
    finished_at = Column(DateTime(timezone=True), nullable=True, comment="任务完成时间")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"<IllustrationImportTask id={self.id} pixiv_id={self.pixiv_id!r} "
            f"status={self.status!r}>"
        )
