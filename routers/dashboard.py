"""Dashboard endpoints providing summarized analytics for the Web UI."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, desc

from models import Group, GroupChatHistory, PrivateChatHistory, User
from registries.engine import engine

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class ActivityEntry(BaseModel):
    """Represents a recent activity item from group or private messages."""

    model_config = ConfigDict(from_attributes=True)

    message_id: int
    scope: str
    scope_id: int
    preview: str | None
    sent_at: datetime | None


class DashboardSummary(BaseModel):
    """Top-level metrics consumed by the dashboard UI."""

    model_config = ConfigDict(from_attributes=True)

    total_groups: int
    active_groups: int
    chat_enabled_groups: int
    total_users: int
    chat_enabled_users: int
    total_group_messages: int
    total_private_messages: int
    recent_activity: list[ActivityEntry]


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(limit: int = 10) -> DashboardSummary:
    """Return summarized metrics and latest activity for the dashboard view."""

    async with engine.new_session() as session:
        total_groups = (await session.execute(select(func.count(Group.id)))).scalar_one()
        active_groups = (
            await session.execute(select(func.count(Group.id)).where(Group.enable.is_(True)))
        ).scalar_one()
        chat_enabled_groups = (
            await session.execute(
                select(func.count(Group.id)).where(Group.enable_chat.is_(True))
            )
        ).scalar_one()

        total_users = (await session.execute(select(func.count(User.id)))).scalar_one()
        chat_enabled_users = (
            await session.execute(select(func.count(User.id)).where(User.enable_chat.is_(True)))
        ).scalar_one()

        total_group_messages = (
            await session.execute(select(func.count(GroupChatHistory.message_id)))
        ).scalar_one()
        total_private_messages = (
            await session.execute(select(func.count(PrivateChatHistory.message_id)))
        ).scalar_one()

        group_messages = (
            await session.execute(
                select(
                    GroupChatHistory.message_id,
                    GroupChatHistory.group_id,
                    GroupChatHistory.text,
                    GroupChatHistory.sent_at,
                    GroupChatHistory.bot_send,
                )
                .order_by(desc(GroupChatHistory.sent_at))
                .limit(limit)
            )
        ).all()

        private_messages = (
            await session.execute(
                select(
                    PrivateChatHistory.message_id,
                    PrivateChatHistory.user_id,
                    PrivateChatHistory.text,
                    PrivateChatHistory.sent_at,
                    PrivateChatHistory.bot_send,
                )
                .order_by(desc(PrivateChatHistory.sent_at))
                .limit(limit)
            )
        ).all()

    def _preview(text: str | None) -> str | None:
        if not text:
            return None
        text = text.strip()
        if len(text) > 120:
            return f"{text[:117]}..."
        return text

    activities: list[ActivityEntry] = []
    for msg in group_messages:
        activities.append(
            ActivityEntry(
                message_id=msg.message_id,
                scope="group_bot" if msg.bot_send else "group",
                scope_id=msg.group_id,
                preview=_preview(msg.text),
                sent_at=msg.sent_at,
            )
        )

    for msg in private_messages:
        activities.append(
            ActivityEntry(
                message_id=msg.message_id,
                scope="private_bot" if msg.bot_send else "private",
                scope_id=msg.user_id,
                preview=_preview(msg.text),
                sent_at=msg.sent_at,
            )
        )

    activities.sort(key=lambda item: item.sent_at or datetime.min, reverse=True)
    activities = activities[:limit]

    return DashboardSummary(
        total_groups=total_groups,
        active_groups=active_groups,
        chat_enabled_groups=chat_enabled_groups,
        total_users=total_users,
        chat_enabled_users=chat_enabled_users,
        total_group_messages=total_group_messages,
        total_private_messages=total_private_messages,
        recent_activity=activities,
    )
