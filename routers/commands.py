"""Endpoints for inspecting bot command execution history."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from registries.command_history_registry import query_history
from utils.api_contract import page_meta, page_offset

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
    page: int
    page_size: int
    pages: int


@router.get("/history", response_model=CommandHistoryResponse)
async def list_command_history(
    command: str | None = Query(default=None, description="Filter by command name"),
    user_id: int | None = Query(default=None, description="Filter by triggering user"),
    success: bool | None = Query(default=None, description="Filter by execution outcome"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    sort_by: str = Query(default="triggered_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> CommandHistoryResponse:
    """Return paginated command execution history entries."""

    allowed_sort_fields = {
        "id", "command", "user_id", "chat_id", "success", "duration_ms", "triggered_at"
    }
    if sort_by not in allowed_sort_fields:
        raise HTTPException(status_code=422, detail=f"不支持的排序字段: {sort_by}")

    total, items = await query_history(
        command=command,
        user_id=user_id,
        success=success,
        limit=page_size,
        offset=page_offset(page, page_size),
        sort_by=sort_by,
        sort_order=sort_order,
    )

    meta = page_meta(total, page, page_size)
    return CommandHistoryResponse(items=items, **meta.model_dump())
