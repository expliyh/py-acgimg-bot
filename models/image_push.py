"""Durable image push plans, batches and per-group delivery receipts."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, JSON, String, Text, func

from configs import config as file_config

from .base import Base


class ImagePushPlan(Base):
    __tablename__ = f"{file_config.db_prefix}image_push_plans"

    id = Column(String(32), primary_key=True)
    name = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    repeat = Column(String(16), nullable=False, default="once")
    due_at = Column(DateTime, nullable=False)
    next_run_at = Column(DateTime, nullable=False, index=True)
    interval_seconds = Column(Integer, nullable=True)
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai")
    target_scope = Column(String(16), nullable=False, default="selected")
    group_ids = Column(JSON, nullable=False, default=list)
    mode = Column(String(24), nullable=False)
    pid = Column(String(64), nullable=True)
    pid_by_group = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (Index("idx_image_push_plan_enabled_due", "enabled", "next_run_at"),)


class ImagePushBatch(Base):
    __tablename__ = f"{file_config.db_prefix}image_push_batches"

    id = Column(String(32), primary_key=True)
    plan_id = Column(String(32), nullable=True, index=True)
    trigger = Column(String(16), nullable=False, default="manual")
    state = Column(String(24), nullable=False, default="pending", index=True)
    due_at = Column(DateTime, nullable=False, index=True)
    config_snapshot = Column(JSON, nullable=False, default=dict)
    summary = Column(JSON, nullable=False, default=dict)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("idx_image_push_batch_queue", "state", "due_at"),)


class ImagePushDelivery(Base):
    __tablename__ = f"{file_config.db_prefix}image_push_deliveries"

    id = Column(String(32), primary_key=True)
    batch_id = Column(String(32), nullable=False, index=True)
    group_id = Column(BigInteger, nullable=False, index=True)
    state = Column(String(24), nullable=False, default="pending", index=True)
    pixiv_id = Column(String(20), nullable=True)
    page = Column(Integer, nullable=True)
    telegram_message_id = Column(BigInteger, nullable=True)
    reason = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("uq_image_push_delivery_batch_group", "batch_id", "group_id", unique=True),
        Index("idx_image_push_delivery_retry", "state", "next_attempt_at"),
    )
