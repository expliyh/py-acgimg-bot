"""Durable, group-scoped moderation state. Times are stored as naive UTC."""

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Index, String, Text

from configs import config

from .base import Base


class GuardRecord(Base):
    __tablename__ = f"{config.db_prefix}guard_records"
    id = Column(String(32), primary_key=True)
    group_id = Column(BigInteger, nullable=False, index=True)
    kind = Column(String(24), nullable=False)
    key = Column(String(160), nullable=False)
    data = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False)
    __table_args__ = (
        Index("uq_guard_record_key", "group_id", "kind", "key", unique=True),
    )


class GuardEvent(Base):
    __tablename__ = f"{config.db_prefix}guard_events"
    id = Column(String(32), primary_key=True)
    group_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=True)
    message_id = Column(BigInteger, nullable=True)
    incident = Column(String(160), nullable=True)
    action = Column(String(24), nullable=False)
    source = Column(String(80), nullable=False)
    status = Column(String(24), nullable=False)
    reason = Column(Text, nullable=False, default="")
    data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, index=True)
    __table_args__ = (
        Index("uq_guard_event_incident", "group_id", "incident", "action", unique=True),
    )


class GuardTask(Base):
    __tablename__ = f"{config.db_prefix}guard_tasks"
    id = Column(String(32), primary_key=True)
    group_id = Column(BigInteger, nullable=False, index=True)
    kind = Column(String(24), nullable=False)
    state = Column(String(24), nullable=False, default="pending")
    due_at = Column(DateTime, nullable=False, index=True)
    data = Column(JSON, nullable=False, default=dict)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)
