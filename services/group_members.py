"""Queries for the member directory shown in the group management console.

Telegram bots cannot enumerate every ordinary group member.  The directory is
therefore built from members the application has observed in message history,
membership/moderation records, or the latest cached administrator list.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Literal

from sqlalchemy import func, select

from models import (
    Group,
    GroupChatHistory,
    GroupGuardPendingVerification,
    GuardEvent,
    GuardRecord,
    User,
)
from registries import engine
from services.moderation import store


MemberRole = Literal["admin", "member"]
MemberState = Literal["warned", "restricted", "exempt"]
SortField = Literal["id", "display_name", "message_count", "last_activity"]


def _record_user_ids(rows: list[GuardRecord]) -> set[int]:
    ids: set[int] = set()
    for row in rows:
        try:
            value = int(row.key)
        except (TypeError, ValueError):
            continue
        if value > 0:
            ids.add(value)
    return ids


async def list_observed_members(
    group_id: int,
    *,
    q: str | None = None,
    role: MemberRole | None = None,
    state: MemberState | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "last_activity",
    sort_order: Literal["asc", "desc"] = "desc",
) -> dict:
    """Return a paginated, group-isolated directory of observed members."""

    settings = await store.policy(group_id)
    warning_since = store.now() - timedelta(days=settings.warning_days)

    async with engine.new_session() as session:
        group = await session.get(Group, group_id)
        if group is None:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "pages": 0,
            }
        admin_ids = {
            int(value)
            for value in (group.admin_ids or [])
            if isinstance(value, int) or str(value).lstrip("-").isdigit()
        }

        history_ids = set(
            (
                await session.scalars(
                    select(GroupChatHistory.user_id).where(
                        GroupChatHistory.group_id == group_id
                    )
                )
            ).all()
        )
        event_ids = set(
            (
                await session.scalars(
                    select(GuardEvent.user_id).where(
                        GuardEvent.group_id == group_id,
                        GuardEvent.user_id.is_not(None),
                    )
                )
            ).all()
        )
        records = (
            await session.scalars(
                select(GuardRecord).where(
                    GuardRecord.group_id == group_id,
                    GuardRecord.kind.in_(("exempt", "restriction", "bot_approval")),
                )
            )
        ).all()
        record_ids = _record_user_ids(records)
        pending_ids = set(
            (
                await session.scalars(
                    select(GroupGuardPendingVerification.user_id).where(
                        GroupGuardPendingVerification.group_id == group_id
                    )
                )
            ).all()
        )

        member_ids = {
            int(value)
            for value in (
                history_ids | event_ids | record_ids | pending_ids | admin_ids
            )
            if value is not None
        }

        if not member_ids:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "pages": 0,
            }

        profiles = {
            user.id: user
            for user in (
                await session.scalars(select(User).where(User.id.in_(member_ids)))
            ).all()
        }
        message_stats = {
            user_id: (count, last_activity)
            for user_id, count, last_activity in (
                await session.execute(
                    select(
                        GroupChatHistory.user_id,
                        func.count(GroupChatHistory.message_id),
                        func.max(GroupChatHistory.sent_at),
                    )
                    .where(
                        GroupChatHistory.group_id == group_id,
                        GroupChatHistory.user_id.in_(member_ids),
                    )
                    .group_by(GroupChatHistory.user_id)
                )
            ).all()
        }
        warning_counts = defaultdict(int)
        for event in (
            await session.scalars(
                select(GuardEvent).where(
                    GuardEvent.group_id == group_id,
                    GuardEvent.user_id.in_(member_ids),
                    GuardEvent.action == "warn",
                    GuardEvent.status == "success",
                    GuardEvent.created_at >= warning_since,
                )
            )
        ).all():
            if event.user_id is not None:
                warning_counts[event.user_id] += 1

        restriction_ids: set[int] = set()
        exempt_ids: set[int] = set()
        for row in records:
            try:
                user_id = int(row.key)
            except (TypeError, ValueError):
                continue
            if row.kind == "exempt" and row.enabled:
                exempt_ids.add(user_id)
            elif row.kind == "restriction" and row.enabled:
                # A durable restriction row is authoritative while an
                # operation is applying, active, or uncertain.  The existing
                # member endpoint exposes the record itself, so retain the
                # same semantics here instead of hiding an in-flight/unknown
                # Telegram state from the directory.
                restriction_ids.add(user_id)

        verification_states = {
            row.user_id: row.state
            for row in (
                await session.scalars(
                    select(GroupGuardPendingVerification).where(
                        GroupGuardPendingVerification.group_id == group_id,
                        GroupGuardPendingVerification.user_id.in_(member_ids),
                    )
                )
            ).all()
        }

    items = []
    query = (q or "").strip().casefold()
    for user_id in member_ids:
        profile = profiles.get(user_id)
        # User profiles are optional because ordinary members may only have
        # been seen in a message/update. Keep the row useful and explicit
        # instead of exposing a blank name in that case.
        display_name = (
            profile.nick_name
            if profile and profile.nick_name
            else f"用户 {user_id}"
        )
        username = profile.username if profile and profile.username else None
        role_value: MemberRole = "admin" if user_id in admin_ids else "member"
        warning_count = warning_counts.get(user_id, 0)
        restriction_active = user_id in restriction_ids
        exempt = user_id in exempt_ids

        if role and role_value != role:
            continue
        if state == "warned" and warning_count <= 0:
            continue
        if state == "restricted" and not restriction_active:
            continue
        if state == "exempt" and not exempt:
            continue
        if query:
            haystack = " ".join(
                value for value in (str(user_id), display_name or "", username or "")
            ).casefold()
            if query not in haystack:
                continue

        sources = []
        if user_id in history_ids:
            sources.append("message")
        if user_id in admin_ids:
            sources.append("admin")
        if user_id in event_ids or user_id in record_ids or user_id in pending_ids:
            sources.append("moderation")
        count, last_activity = message_stats.get(user_id, (0, None))
        items.append(
            {
                "user_id": user_id,
                "display_name": display_name,
                "username": username,
                "role": role_value,
                "source": sources,
                "message_count": int(count or 0),
                "last_activity": last_activity,
                "warning_count": warning_count,
                "restriction_active": restriction_active,
                "exempt": exempt,
                "verification_state": verification_states.get(user_id),
            }
        )

    def sort_value(item: dict):
        value = item["user_id"] if sort_by == "id" else item[sort_by]
        if sort_by == "display_name" and value is not None:
            return str(value).casefold()
        return value

    # Keep members without activity/name at the end in either direction. A
    # reverse sort on a tuple containing a null marker would otherwise move
    # them to the top for descending queries.
    present = [item for item in items if sort_value(item) is not None]
    missing = [item for item in items if sort_value(item) is None]
    present.sort(
        key=lambda item: (sort_value(item), item["user_id"]),
        reverse=sort_order == "desc",
    )
    missing.sort(key=lambda item: item["user_id"], reverse=sort_order == "desc")
    items = present + missing
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    }
