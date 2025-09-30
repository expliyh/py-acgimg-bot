"""Endpoints for inspecting bot command execution history."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from registries.command_history_registry import query_history

router = APIRouter(prefix="/api/commands", tags=["commands"])


class CommandHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    command: str
    user_id: int | None
    chat_id: int | None
    chat_type: str | None
    message_id: int | None
    arguments: list[str] | None
    raw_text: str | None
    success: bool
    error_message: str | None
    duration_ms: int | None
    triggered_at: datetime


class CommandHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    items: list[CommandHistoryEntry]


@router.get("/history", response_model=CommandHistoryResponse)
async def list_command_history(
    command: str | None = Query(default=None, description="Filter by command name"),
    user_id: int | None = Query(default=None, description="Filter by triggering user"),
    success: bool | None = Query(default=None, description="Filter by execution outcome"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CommandHistoryResponse:
    """Return paginated command execution history entries."""

    total, items = await query_history(
        command=command,
        user_id=user_id,
        success=success,
        limit=limit,
        offset=offset,
    )

    return CommandHistoryResponse(total=total, items=items)
