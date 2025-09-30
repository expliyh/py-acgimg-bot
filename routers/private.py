"""Private chat management API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast, desc, func, or_, select

from defines import MessageType, UserStatus
from models import PrivateChatHistory, User
from registries.engine import engine

router = APIRouter(prefix="/api/private", tags=["private"])


class EnumOption(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    label: str
    value: str


class PrivateMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    message_id: int
    type: MessageType
    bot_send: bool
    text: str | None
    sent_at: datetime | None


class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: int
    nick_name: str | None
    status: UserStatus
    enable_chat: bool
    sanity_limit: int
    allow_r18g: bool


class PrivateUserListItem(UserBase):
    message_count: int
    last_activity: datetime | None


class PrivateUserListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    items: list[PrivateUserListItem]


class PrivateUserDetail(PrivateUserListItem):
    recent_messages: list[PrivateMessage]


class PrivateUserUpdate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    nick_name: str | None = None
    enable_chat: bool | None = None
    sanity_limit: int | None = Field(default=None, ge=0)
    allow_r18g: bool | None = None
    status: UserStatus | None = None


def _apply_filters(stmt, *, search: str | None, chat_enabled: bool | None, status: UserStatus | None):
    if search:
        like_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                cast(User.id, String).ilike(like_term),
                User.nick_name.ilike(like_term),
            )
        )
    if chat_enabled is not None:
        stmt = stmt.where(User.enable_chat.is_(chat_enabled))
    if status is not None:
        stmt = stmt.where(User.status == status)
    return stmt


@router.get("/meta", response_model=dict)
async def get_private_meta() -> dict[str, Any]:
    """Return enum metadata for private user management."""

    return {
        "statuses": [
            EnumOption(label=status.name.title(), value=status.value) for status in UserStatus
        ]
    }


@router.get("/users", response_model=PrivateUserListResponse)
async def list_private_users(
    q: str | None = Query(default=None, description="Search by user id or nickname"),
    chat_enabled: bool | None = Query(default=None, description="Filter by chat availability"),
    status: UserStatus | None = Query(default=None, description="Filter by user status"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PrivateUserListResponse:
    """List private users along with message statistics."""

    async with engine.new_session() as session:
        stmt = (
            select(
                User,
                func.count(PrivateChatHistory.message_id).label("message_count"),
                func.max(PrivateChatHistory.sent_at).label("last_activity"),
            )
            .outerjoin(PrivateChatHistory, PrivateChatHistory.user_id == User.id)
            .group_by(User.id)
        )

        stmt = _apply_filters(stmt, search=q, chat_enabled=chat_enabled, status=status)
        stmt = stmt.order_by(User.id).limit(limit).offset(offset)
        result = await session.execute(stmt)
        rows = result.all()

        count_stmt = select(func.count()).select_from(User)
        count_stmt = _apply_filters(count_stmt, search=q, chat_enabled=chat_enabled, status=status)
        total = (await session.execute(count_stmt)).scalar_one()

    items = [
        PrivateUserListItem(
            id=row.User.id,
            nick_name=row.User.nick_name,
            status=row.User.status,
            enable_chat=row.User.enable_chat,
            sanity_limit=row.User.sanity_limit,
            allow_r18g=row.User.allow_r18g,
            message_count=row.message_count or 0,
            last_activity=row.last_activity,
        )
        for row in rows
    ]

    return PrivateUserListResponse(total=total, items=items)


@router.get("/users/{user_id}", response_model=PrivateUserDetail)
async def get_private_user(
    user_id: int, recent_limit: int = Query(default=20, ge=1, le=50)
) -> PrivateUserDetail:
    """Retrieve detail and recent activity for a single user."""

    async with engine.new_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        stats = (
            await session.execute(
                select(
                    func.count(PrivateChatHistory.message_id),
                    func.max(PrivateChatHistory.sent_at),
                ).where(PrivateChatHistory.user_id == user_id)
            )
        ).one()
        message_count, last_activity = stats

        recent = (
            await session.execute(
                select(PrivateChatHistory)
                .where(PrivateChatHistory.user_id == user_id)
                .order_by(desc(PrivateChatHistory.sent_at))
                .limit(recent_limit)
            )
        ).scalars().all()

    recent_messages = [
        PrivateMessage(
            message_id=msg.message_id,
            type=msg.type,
            bot_send=msg.bot_send,
            text=msg.text,
            sent_at=msg.sent_at,
        )
        for msg in recent
    ]

    return PrivateUserDetail(
        id=user.id,
        nick_name=user.nick_name,
        status=user.status,
        enable_chat=user.enable_chat,
        sanity_limit=user.sanity_limit,
        allow_r18g=user.allow_r18g,
        message_count=message_count or 0,
        last_activity=last_activity,
        recent_messages=recent_messages,
    )


@router.put("/users/{user_id}", response_model=PrivateUserDetail)
async def update_private_user(user_id: int, payload: PrivateUserUpdate) -> PrivateUserDetail:
    """Update private user preferences and return the updated detail."""

    async with engine.new_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        await session.commit()
        await session.refresh(user)

        stats = (
            await session.execute(
                select(
                    func.count(PrivateChatHistory.message_id),
                    func.max(PrivateChatHistory.sent_at),
                ).where(PrivateChatHistory.user_id == user_id)
            )
        ).one()
        message_count, last_activity = stats

        recent = (
            await session.execute(
                select(PrivateChatHistory)
                .where(PrivateChatHistory.user_id == user_id)
                .order_by(desc(PrivateChatHistory.sent_at))
                .limit(20)
            )
        ).scalars().all()

    recent_messages = [
        PrivateMessage(
            message_id=msg.message_id,
            type=msg.type,
            bot_send=msg.bot_send,
            text=msg.text,
            sent_at=msg.sent_at,
        )
        for msg in recent
    ]

    return PrivateUserDetail(
        id=user.id,
        nick_name=user.nick_name,
        status=user.status,
        enable_chat=user.enable_chat,
        sanity_limit=user.sanity_limit,
        allow_r18g=user.allow_r18g,
        message_count=message_count or 0,
        last_activity=last_activity,
        recent_messages=recent_messages,
    )


@router.get("/users/{user_id}/history", response_model=list[PrivateMessage])
async def get_private_history(
    user_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = Query(default=None, description="Messages before timestamp"),
) -> list[PrivateMessage]:
    """Return a slice of private chat history for a user."""

    async with engine.new_session() as session:
        stmt = select(PrivateChatHistory).where(PrivateChatHistory.user_id == user_id)
        if before is not None:
            stmt = stmt.where(PrivateChatHistory.sent_at < before)
        stmt = stmt.order_by(desc(PrivateChatHistory.sent_at)).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return [
        PrivateMessage(
            message_id=row.message_id,
            type=row.type,
            bot_send=row.bot_send,
            text=row.text,
            sent_at=row.sent_at,
        )
        for row in rows
    ]
