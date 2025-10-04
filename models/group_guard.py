from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, func, Index

from configs import config as file_config
from .base import Base


class GroupGuardSettings(Base):
    __tablename__ = f"{file_config.db_prefix}group_guard_settings"

    group_id = Column(BigInteger, primary_key=True, autoincrement=False)
    verification_enabled = Column(Boolean, nullable=False, default=False)
    verification_timeout = Column(Integer, nullable=False, default=60)
    verification_message = Column(Text, nullable=True)
    keyword_filter_enabled = Column(Boolean, nullable=False, default=False)
    kick_on_timeout = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class GroupGuardKeywordRule(Base):
    __tablename__ = f"{file_config.db_prefix}group_guard_keyword_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, nullable=False, index=True)
    pattern = Column(Text, nullable=False)
    is_regex = Column(Boolean, nullable=False, default=False)
    case_sensitive = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_guard_keyword_group_pattern", "group_id", "pattern"),
    )


class GroupGuardPendingVerification(Base):
    __tablename__ = f"{file_config.db_prefix}group_guard_pending_verifications"

    group_id = Column(BigInteger, primary_key=True, autoincrement=False)
    user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    message_id = Column(BigInteger, nullable=True)
    token = Column(String(32), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_guard_pending_expires", "expires_at"),
    )
