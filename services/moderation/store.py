from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from weakref import WeakValueDictionary

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from models import GroupGuardSettings, GuardEvent, GuardRecord, GuardTask
from registries import engine
from services import group_guard

from .schemas import VERIFICATION_MESSAGE_MAX_LENGTH, AIConfig, Policy

LEGACY = {
    "verification_enabled",
    "verification_timeout",
    "verification_message",
    "kick_on_timeout",
    "keyword_filter_enabled",
}
_locks: WeakValueDictionary = WeakValueDictionary()


def lock(group_id: int) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), group_id)
    value = _locks.get(key)
    if value is None:
        value = asyncio.Lock()
        _locks[key] = value
    return value


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid() -> str:
    return uuid.uuid4().hex


def dump(row) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def json_data(value):
    def encode(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Unsupported persisted value: {type(obj).__name__}")

    return json.loads(json.dumps(value, default=encode))


async def policy(group_id: int) -> Policy:
    repaired = False
    async with engine.new_session() as session:
        row = await session.get(GroupGuardSettings, group_id)
        if row is None:
            return Policy()
        data = dict(row.policy or {})
        data.update({key: getattr(row, key) for key in LEGACY})
        message = row.verification_message
        if message and len(message) > VERIFICATION_MESSAGE_MAX_LENGTH:
            message = message[:VERIFICATION_MESSAGE_MAX_LENGTH]
            row.verification_message = message
            data["verification_message"] = message
            await session.commit()
            repaired = True
    if repaired:
        await group_guard._invalidate_settings_cache(group_id)
    return Policy.model_validate(data)


async def save_policy(group_id: int, changes: dict) -> Policy:
    async with lock(group_id):
        value = Policy.model_validate((await policy(group_id)).model_dump() | changes)
        async with engine.new_session() as session:
            row = await session.get(GroupGuardSettings, group_id)
            if row is None:
                row = GroupGuardSettings(group_id=group_id)
                session.add(row)
            data = value.model_dump()
            for key in LEGACY:
                setattr(row, key, data.pop(key))
            row.policy = data
            await session.commit()
        await group_guard._invalidate_settings_cache(group_id)
        return value


async def records(group_id: int, kind: str, *, enabled=False) -> list[dict]:
    async with engine.new_session() as session:
        stmt = select(GuardRecord).where(
            GuardRecord.group_id == group_id, GuardRecord.kind == kind
        )
        if enabled:
            stmt = stmt.where(GuardRecord.enabled.is_(True))
        rows = (
            await session.scalars(stmt.order_by(GuardRecord.created_at, GuardRecord.id))
        ).all()
        return [dump(row) for row in rows]


async def record(group_id: int, kind: str, key: str) -> dict | None:
    async with engine.new_session() as session:
        row = await session.scalar(
            select(GuardRecord).where(
                GuardRecord.group_id == group_id,
                GuardRecord.kind == kind,
                GuardRecord.key == key,
            )
        )
        return dump(row) if row else None


async def put_record(
    group_id: int, kind: str, key: str, data: dict, enabled=True
) -> dict:
    async with engine.new_session() as session:
        row = await session.scalar(
            select(GuardRecord).where(
                GuardRecord.group_id == group_id,
                GuardRecord.kind == kind,
                GuardRecord.key == key,
            )
        )
        if row is None:
            row = GuardRecord(
                id=uid(), group_id=group_id, kind=kind, key=key, created_at=now()
            )
            session.add(row)
        row.data, row.enabled = json_data(data), enabled
        result = dump(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            row = await session.scalar(
                select(GuardRecord).where(
                    GuardRecord.group_id == group_id,
                    GuardRecord.kind == kind,
                    GuardRecord.key == key,
                )
            )
            if row is None:
                raise
            row.data, row.enabled = json_data(data), enabled
            result = dump(row)
            await session.commit()
        return result


async def remove_record(group_id: int, kind: str, key: str) -> bool:
    async with engine.new_session() as session:
        result = await session.execute(
            delete(GuardRecord).where(
                GuardRecord.group_id == group_id,
                GuardRecord.kind == kind,
                GuardRecord.key == key,
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def event(
    group_id: int,
    action: str,
    *,
    source="system",
    status="success",
    reason="",
    user_id=None,
    message_id=None,
    incident=None,
    data=None,
) -> tuple[dict, bool]:
    async with engine.new_session() as session:
        row = GuardEvent(
            id=uid(),
            group_id=group_id,
            user_id=user_id,
            message_id=message_id,
            incident=incident,
            action=action,
            source=source,
            status=status,
            reason=reason,
            data=json_data(data or {}),
            created_at=now(),
        )
        session.add(row)
        result = dump(row)
        try:
            await session.commit()
            return result, True
        except IntegrityError:
            await session.rollback()
            if incident is None:
                raise
            existing = await session.scalar(
                select(GuardEvent).where(
                    GuardEvent.group_id == group_id,
                    GuardEvent.incident == incident,
                    GuardEvent.action == action,
                )
            )
            if existing is None:
                raise
            return dump(existing), False


async def finish_event(event_id: str, status: str, data: dict) -> dict:
    async with engine.new_session() as session:
        row = await session.get(GuardEvent, event_id)
        row.status, row.data = status, json_data(data)
        result = dump(row)
        await session.commit()
        return result


async def warnings(group_id: int, user_id: int) -> list[dict]:
    settings = await policy(group_id)
    async with engine.new_session() as session:
        rows = (
            await session.scalars(
                select(GuardEvent)
                .where(
                    GuardEvent.group_id == group_id,
                    GuardEvent.user_id == user_id,
                    GuardEvent.action == "warn",
                    GuardEvent.status == "success",
                    GuardEvent.created_at
                    >= now() - timedelta(days=settings.warning_days),
                )
                .order_by(GuardEvent.created_at.desc())
            )
        ).all()
        return [dump(row) for row in rows]


async def task(group_id: int, kind: str, due_at: datetime, data: dict) -> str:
    if due_at.tzinfo:
        due_at = due_at.astimezone(timezone.utc).replace(tzinfo=None)
    task_id = uid()
    async with engine.new_session() as session:
        session.add(
            GuardTask(
                id=task_id,
                group_id=group_id,
                kind=kind,
                due_at=due_at,
                data=json_data(data),
                state="pending",
                created_at=now(),
            )
        )
        await session.commit()
    return task_id


async def ai_config() -> AIConfig:
    row = await record(0, "ai_config", "default")
    return AIConfig.model_validate(row["data"] if row else {})


async def save_ai_config(config: AIConfig) -> dict:
    previous = await ai_config()
    data = config.model_dump()
    if data["api_key"] is None:
        data["api_key"] = previous.api_key
    await put_record(0, "ai_config", "default", data)
    return public_ai_config(AIConfig.model_validate(data))


def public_ai_config(config: AIConfig) -> dict:
    return config.model_dump(exclude={"api_key"}) | {
        "has_api_key": bool(config.api_key)
    }
