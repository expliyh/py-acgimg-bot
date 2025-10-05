from __future__ import annotations

import asyncio
import logging
import random
import re
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    GroupGuardKeywordRule,
    GroupGuardPendingVerification,
    GroupGuardSettings,
)
from registries import engine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GuardSettings:
    group_id: int
    verification_enabled: bool
    verification_timeout: int
    verification_message: str | None
    keyword_filter_enabled: bool
    kick_on_timeout: bool


@dataclass(slots=True)
class KeywordRule:
    id: int
    pattern: str
    is_regex: bool
    case_sensitive: bool


@dataclass(slots=True)
class PendingVerification:
    group_id: int
    user_id: int
    message_id: int | None
    token: str
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return current >= expires


_SETTINGS_CACHE_TTL = timedelta(seconds=30)
_KEYWORD_CACHE_TTL = timedelta(seconds=30)
MAX_KEYWORD_PATTERN_LENGTH = 512

_settings_cache: dict[int, tuple[GuardSettings, datetime]] = {}
_keyword_cache: dict[int, tuple[list[KeywordRule], datetime]] = {}
_cache_lock = asyncio.Lock()


async def get_guard_settings(group_id: int) -> GuardSettings:
    async with _cache_lock:
        cached = _settings_cache.get(group_id)
        if cached:
            value, stored_at = cached
            if datetime.now(timezone.utc) - stored_at <= _SETTINGS_CACHE_TTL:
                return value

    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = await session.get(GroupGuardSettings, group_id)
        if record is None:
            record = GroupGuardSettings(group_id=group_id)
            session.add(record)
            await session.commit()
            await session.refresh(record)

        settings = GuardSettings(
            group_id=record.group_id,
            verification_enabled=bool(record.verification_enabled),
            verification_timeout=int(record.verification_timeout or 60),
            verification_message=record.verification_message,
            keyword_filter_enabled=bool(record.keyword_filter_enabled),
            kick_on_timeout=bool(record.kick_on_timeout),
        )

    async with _cache_lock:
        _settings_cache[group_id] = (settings, datetime.now(timezone.utc))

    return settings


async def _invalidate_settings_cache(group_id: int) -> None:
    async with _cache_lock:
        _settings_cache.pop(group_id, None)


async def set_verification_enabled(group_id: int, enabled: bool) -> GuardSettings:
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = await session.get(GroupGuardSettings, group_id)
        if record is None:
            record = GroupGuardSettings(group_id=group_id)
            session.add(record)
        record.verification_enabled = bool(enabled)
        await session.commit()
    await _invalidate_settings_cache(group_id)
    return await get_guard_settings(group_id)


async def set_keyword_filter_enabled(group_id: int, enabled: bool) -> GuardSettings:
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = await session.get(GroupGuardSettings, group_id)
        if record is None:
            record = GroupGuardSettings(group_id=group_id)
            session.add(record)
        record.keyword_filter_enabled = bool(enabled)
        await session.commit()
    await _invalidate_settings_cache(group_id)
    await _invalidate_keyword_cache(group_id)
    return await get_guard_settings(group_id)


async def set_verification_timeout(group_id: int, timeout_seconds: int) -> GuardSettings:
    timeout = max(15, min(timeout_seconds, 3600))
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = await session.get(GroupGuardSettings, group_id)
        if record is None:
            record = GroupGuardSettings(group_id=group_id)
            session.add(record)
        record.verification_timeout = timeout
        await session.commit()
    await _invalidate_settings_cache(group_id)
    return await get_guard_settings(group_id)


async def set_verification_message(group_id: int, message: str | None) -> GuardSettings:
    normalized = message.strip() if message else None
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = await session.get(GroupGuardSettings, group_id)
        if record is None:
            record = GroupGuardSettings(group_id=group_id)
            session.add(record)
        record.verification_message = normalized
        await session.commit()
    await _invalidate_settings_cache(group_id)
    return await get_guard_settings(group_id)


async def set_kick_on_timeout(group_id: int, enabled: bool) -> GuardSettings:
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = await session.get(GroupGuardSettings, group_id)
        if record is None:
            record = GroupGuardSettings(group_id=group_id)
            session.add(record)
        record.kick_on_timeout = bool(enabled)
        await session.commit()
    await _invalidate_settings_cache(group_id)
    return await get_guard_settings(group_id)


async def list_keyword_rules(group_id: int) -> list[KeywordRule]:
    async with _cache_lock:
        cached = _keyword_cache.get(group_id)
        if cached:
            value, stored_at = cached
            if datetime.now(timezone.utc) - stored_at <= _KEYWORD_CACHE_TTL:
                return list(value)

    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        result = await session.execute(
            select(GroupGuardKeywordRule).where(GroupGuardKeywordRule.group_id == group_id)
        )
        rules = [
            KeywordRule(
                id=rule.id,
                pattern=rule.pattern,
                is_regex=bool(rule.is_regex),
                case_sensitive=bool(rule.case_sensitive),
            )
            for rule in result.scalars().all()
        ]

    async with _cache_lock:
        _keyword_cache[group_id] = (rules, datetime.now(timezone.utc))

    return list(rules)


async def _invalidate_keyword_cache(group_id: int) -> None:
    async with _cache_lock:
        _keyword_cache.pop(group_id, None)


async def add_keyword_rule(
    group_id: int,
    pattern: str,
    *,
    is_regex: bool = False,
    case_sensitive: bool = False,
) -> KeywordRule:
    raw_pattern = (pattern or "").strip()
    if not raw_pattern:
        raise ValueError("关键字不能为空")

    if len(raw_pattern) > MAX_KEYWORD_PATTERN_LENGTH:
        raise ValueError(
            f"关键字长度不能超过 {MAX_KEYWORD_PATTERN_LENGTH} 个字符"
        )

    if is_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            re.compile(raw_pattern, flags=flags)
        except re.error as exc:
            raise ValueError(f"正则表达式无效: {exc}") from exc

    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = GroupGuardKeywordRule(
            group_id=group_id,
            pattern=raw_pattern,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

    await _invalidate_keyword_cache(group_id)

    return KeywordRule(
        id=record.id,
        pattern=record.pattern,
        is_regex=bool(record.is_regex),
        case_sensitive=bool(record.case_sensitive),
    )


async def remove_keyword_rule(group_id: int, rule_id: int) -> bool:
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        result = await session.execute(
            delete(GroupGuardKeywordRule)
            .where(
                (GroupGuardKeywordRule.id == rule_id)
                & (GroupGuardKeywordRule.group_id == group_id)
            )
        )
        await session.commit()
        removed = result.rowcount or 0

    if removed:
        await _invalidate_keyword_cache(group_id)
    return bool(removed)


async def clear_keyword_rules(group_id: int) -> int:
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        result = await session.execute(
            delete(GroupGuardKeywordRule).where(GroupGuardKeywordRule.group_id == group_id)
        )
        await session.commit()
        removed = result.rowcount or 0
    await _invalidate_keyword_cache(group_id)
    return removed


async def upsert_pending_verification(
    *,
    group_id: int,
    user_id: int,
    message_id: int | None,
    token: str,
    expires_at: datetime,
) -> PendingVerification:
    expires_at = _ensure_timezone(expires_at)
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = await session.get(GroupGuardPendingVerification, (group_id, user_id))
        if record is None:
            record = GroupGuardPendingVerification(
                group_id=group_id,
                user_id=user_id,
                message_id=message_id,
                token=token,
                expires_at=expires_at,
            )
            session.add(record)
        else:
            record.message_id = message_id
            record.token = token
            record.expires_at = expires_at
        await session.commit()
        await session.refresh(record)

    return PendingVerification(
        group_id=record.group_id,
        user_id=record.user_id,
        message_id=record.message_id,
        token=record.token,
        expires_at=_ensure_timezone(record.expires_at),
    )


async def get_pending_verification(group_id: int, user_id: int) -> PendingVerification | None:
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        record = await session.get(GroupGuardPendingVerification, (group_id, user_id))
        if record is None:
            return None
        return PendingVerification(
            group_id=record.group_id,
            user_id=record.user_id,
            message_id=record.message_id,
            token=record.token,
            expires_at=_ensure_timezone(record.expires_at),
        )


async def get_pending_verification_by_token(token: str) -> PendingVerification | None:
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        result = await session.execute(
            select(GroupGuardPendingVerification).where(
                GroupGuardPendingVerification.token == token
            )
        )
        record = result.scalars().first()
        if record is None:
            return None
        return PendingVerification(
            group_id=record.group_id,
            user_id=record.user_id,
            message_id=record.message_id,
            token=record.token,
            expires_at=_ensure_timezone(record.expires_at),
        )


async def delete_pending_verification(group_id: int, user_id: int) -> None:
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        await session.execute(
            delete(GroupGuardPendingVerification).where(
                (GroupGuardPendingVerification.group_id == group_id)
                & (GroupGuardPendingVerification.user_id == user_id)
            )
        )
        await session.commit()


async def cleanup_expired_pending(now: datetime | None = None) -> int:
    current = _ensure_timezone(now or datetime.now(timezone.utc))
    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        result = await session.execute(
            delete(GroupGuardPendingVerification).where(
                GroupGuardPendingVerification.expires_at <= current
            )
        )
        await session.commit()
        return result.rowcount or 0


async def ensure_settings(group_ids: Iterable[int]) -> None:
    """Ensure settings rows exist for the provided group IDs."""

    ids = list({gid for gid in group_ids if gid})
    if not ids:
        return

    async with engine.new_session() as session:
        session = session  # type: AsyncSession
        existing = await session.execute(
            select(GroupGuardSettings.group_id).where(GroupGuardSettings.group_id.in_(ids))
        )
        existing_ids = set(existing.scalars().all())
        missing = [gid for gid in ids if gid not in existing_ids]
        if not missing:
            return
        session.add_all(GroupGuardSettings(group_id=gid) for gid in missing)
        await session.commit()


def generate_token(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

