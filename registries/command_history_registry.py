"""Persistence helpers for command execution history."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import CommandHistory

from .engine import engine


async def record_command_execution(
    *,
    command: str,
    user_id: int | None,
    chat_id: int | None,
    chat_type: str | None,
    message_id: int | None,
    arguments: Sequence[str] | None,
    raw_text: str | None,
    success: bool,
    error_message: str | None,
    duration_ms: int | None,
    triggered_at: datetime,
) -> CommandHistory:
    """Persist a single command execution entry."""

    payload = CommandHistory(
        command=command,
        user_id=user_id,
        chat_id=chat_id,
        chat_type=chat_type,
        message_id=message_id,
        arguments=list(arguments) if arguments is not None else None,
        raw_text=raw_text,
        success=success,
        error_message=error_message,
        duration_ms=duration_ms,
        triggered_at=triggered_at,
    )

    async with engine.new_session() as session:
        session: AsyncSession = session
        session.add(payload)
        await session.commit()
        await session.refresh(payload)
        return payload


async def query_history(
    *,
    command: str | None = None,
    user_id: int | None = None,
    success: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[CommandHistory]]:
    """Retrieve paginated command history entries applying optional filters."""

    async with engine.new_session() as session:
        session: AsyncSession = session

        filters = []
        if command:
            filters.append(CommandHistory.command == command)
        if user_id is not None:
            filters.append(CommandHistory.user_id == user_id)
        if success is not None:
            filters.append(CommandHistory.success.is_(success))

        stmt = select(CommandHistory)
        if filters:
            stmt = stmt.where(and_(*filters))
        stmt = stmt.order_by(desc(CommandHistory.triggered_at)).limit(limit).offset(offset)

        result = await session.execute(stmt)
        items = result.scalars().all()

        count_stmt = select(func.count()).select_from(CommandHistory)
        if filters:
            count_stmt = count_stmt.where(and_(*filters))
        total = (await session.execute(count_stmt)).scalar_one()

        return total, items
