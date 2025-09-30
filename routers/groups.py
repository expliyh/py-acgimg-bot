"""Group management endpoints for administrative operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast, desc, func, or_, select

from defines import GroupChatMode, GroupStatus
from models import Group, GroupChatHistory
from registries.engine import engine

router = APIRouter(prefix="/api/groups", tags=["groups"])


class EnumOption(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    label: str
    value: str


class ChatMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    message_id: int
    user_id: int
    type: str
    bot_send: bool
    text: str | None
    sent_at: datetime | None


class GroupBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: int
    name: str | None
    status: GroupStatus
    enable: bool
    enable_chat: bool
    chat_mode: GroupChatMode
    sanity_limit: int
    allow_r18g: bool
    allow_setu: bool
    admin_ids: list[int]


class GroupListItem(GroupBase):
    message_count: int
    last_activity: datetime | None


class GroupListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    items: list[GroupListItem]


class GroupDetail(GroupListItem):
    recent_messages: list[ChatMessage]


class GroupUpdate(BaseModel):
    """Payload accepted to update a group's configurable options."""

    model_config = ConfigDict(use_enum_values=True)

    name: str | None = None
    enable: bool | None = None
    enable_chat: bool | None = None
    chat_mode: GroupChatMode | None = Field(default=None)
    sanity_limit: int | None = Field(default=None, ge=0)
    allow_r18g: bool | None = None
    allow_setu: bool | None = None
    admin_ids: list[int] | None = None


def _apply_filters(stmt, *, search: str | None, enable: bool | None, chat_enabled: bool | None):
    if search:
        like_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Group.name.ilike(like_term),
                cast(Group.id, String).ilike(like_term),
            )
        )
    if enable is not None:
        stmt = stmt.where(Group.enable.is_(enable))
    if chat_enabled is not None:
        stmt = stmt.where(Group.enable_chat.is_(chat_enabled))
    return stmt


@router.get("/meta", response_model=dict)
async def get_group_meta() -> dict[str, Any]:
    """Return enum metadata required by the management console."""

    return {
        "chat_modes": [
            EnumOption(label=mode.name.title(), value=mode.value) for mode in GroupChatMode
        ],
        "statuses": [
            EnumOption(label=status.name.title(), value=status.value) for status in GroupStatus
        ],
    }


@router.get("", response_model=GroupListResponse)
async def list_groups(
    q: str | None = Query(default=None, description="Search by group id or name"),
    enable: bool | None = Query(default=None, description="Filter by enabled flag"),
    chat_enabled: bool | None = Query(
        default=None, description="Filter by AI chat enabled flag"
    ),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> GroupListResponse:
    """List groups with aggregated metadata for the administrative UI."""

    async with engine.new_session() as session:
        stmt = (
            select(
                Group,
                func.count(GroupChatHistory.message_id).label("message_count"),
                func.max(GroupChatHistory.sent_at).label("last_activity"),
            )
            .outerjoin(GroupChatHistory, GroupChatHistory.group_id == Group.id)
            .group_by(Group.id)
        )

        stmt = _apply_filters(stmt, search=q, enable=enable, chat_enabled=chat_enabled)
        stmt = stmt.order_by(Group.id).limit(limit).offset(offset)
        result = await session.execute(stmt)
        rows = result.all()

        count_stmt = select(func.count()).select_from(Group)
        count_stmt = _apply_filters(count_stmt, search=q, enable=enable, chat_enabled=chat_enabled)
        total = (await session.execute(count_stmt)).scalar_one()

    items = [
        GroupListItem(
            id=row.Group.id,
            name=row.Group.name,
            status=row.Group.status,
            enable=row.Group.enable,
            enable_chat=row.Group.enable_chat,
            chat_mode=row.Group.chat_mode,
            sanity_limit=row.Group.sanity_limit,
            allow_r18g=row.Group.allow_r18g,
            allow_setu=row.Group.allow_setu,
            admin_ids=row.Group.admin_ids or [],
            message_count=row.message_count or 0,
            last_activity=row.last_activity,
        )
        for row in rows
    ]

    return GroupListResponse(total=total, items=items)


@router.get("/{group_id}", response_model=GroupDetail)
async def get_group_detail(group_id: int, recent_limit: int = Query(default=20, ge=1, le=50)) -> GroupDetail:
    """Retrieve detailed configuration and recent history for a group."""

    async with engine.new_session() as session:
        group = await session.get(Group, group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="Group not found")

        stats = (
            await session.execute(
                select(
                    func.count(GroupChatHistory.message_id),
                    func.max(GroupChatHistory.sent_at),
                ).where(GroupChatHistory.group_id == group_id)
            )
        ).one()
        message_count, last_activity = stats

        recent = (
            await session.execute(
                select(GroupChatHistory)
                .where(GroupChatHistory.group_id == group_id)
                .order_by(desc(GroupChatHistory.sent_at))
                .limit(recent_limit)
            )
        ).scalars().all()

    recent_messages = [
        ChatMessage(
            message_id=msg.message_id,
            user_id=msg.user_id,
            type=msg.type.value,
            bot_send=msg.bot_send,
            text=msg.text,
            sent_at=msg.sent_at,
        )
        for msg in recent
    ]

    return GroupDetail(
        id=group.id,
        name=group.name,
        status=group.status,
        enable=group.enable,
        enable_chat=group.enable_chat,
        chat_mode=group.chat_mode,
        sanity_limit=group.sanity_limit,
        allow_r18g=group.allow_r18g,
        allow_setu=group.allow_setu,
        admin_ids=group.admin_ids or [],
        message_count=message_count or 0,
        last_activity=last_activity,
        recent_messages=recent_messages,
    )


@router.put("/{group_id}", response_model=GroupDetail)
async def update_group(group_id: int, payload: GroupUpdate) -> GroupDetail:
    """Update a group's configuration and return the updated detail object."""

    async with engine.new_session() as session:
        group = await session.get(Group, group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="Group not found")

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(group, field, value)

        await session.commit()
        await session.refresh(group)

        stats = (
            await session.execute(
                select(
                    func.count(GroupChatHistory.message_id),
                    func.max(GroupChatHistory.sent_at),
                ).where(GroupChatHistory.group_id == group_id)
            )
        ).one()
        message_count, last_activity = stats

        recent = (
            await session.execute(
                select(GroupChatHistory)
                .where(GroupChatHistory.group_id == group_id)
                .order_by(desc(GroupChatHistory.sent_at))
                .limit(20)
            )
        ).scalars().all()

    recent_messages = [
        ChatMessage(
            message_id=msg.message_id,
            user_id=msg.user_id,
            type=msg.type.value,
            bot_send=msg.bot_send,
            text=msg.text,
            sent_at=msg.sent_at,
        )
        for msg in recent
    ]

    return GroupDetail(
        id=group.id,
        name=group.name,
        status=group.status,
        enable=group.enable,
        enable_chat=group.enable_chat,
        chat_mode=group.chat_mode,
        sanity_limit=group.sanity_limit,
        allow_r18g=group.allow_r18g,
        allow_setu=group.allow_setu,
        admin_ids=group.admin_ids or [],
        message_count=message_count or 0,
        last_activity=last_activity,
        recent_messages=recent_messages,
    )


@router.get("/{group_id}/history", response_model=list[ChatMessage])
async def get_group_history(
    group_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = Query(default=None, description="Return messages before timestamp"),
) -> list[ChatMessage]:
    """Return a paginated slice of group chat history."""

    async with engine.new_session() as session:
        stmt = select(GroupChatHistory).where(GroupChatHistory.group_id == group_id)
        if before is not None:
            stmt = stmt.where(GroupChatHistory.sent_at < before)
        stmt = stmt.order_by(desc(GroupChatHistory.sent_at)).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return [
        ChatMessage(
            message_id=row.message_id,
            user_id=row.user_id,
            type=row.type.value,
            bot_send=row.bot_send,
            text=row.text,
            sent_at=row.sent_at,
        )
        for row in rows
    ]
