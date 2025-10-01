"""Caching helpers for expensive Telegram Bot API calls."""

from __future__ import annotations

import asyncio
import logging
import pickle
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from telegram import Bot
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from registries import config_registry

try:  # pragma: no cover - optional dependency
    from redis.asyncio import Redis  # type: ignore
except Exception:  # pragma: no cover - redis is optional
    Redis = None

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Value container persisted in cache backends."""

    value: Any
    expires_at: datetime
    stored_at: datetime

    def is_valid(self, *, now: datetime) -> bool:
        return now <= self.expires_at


class CacheBackend(Protocol):
    async def get(self, key: str) -> CacheEntry | None:
        ...

    async def set(self, key: str, entry: CacheEntry, ttl: int) -> None:
        ...

    async def delete(self, key: str) -> None:
        ...

    async def close(self) -> None:
        ...


class InMemoryCacheBackend:
    """A simple asyncio-safe in-memory cache backend."""

    def __init__(self) -> None:
        self._data: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> CacheEntry | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            now = datetime.now(timezone.utc)
            if entry.expires_at + timedelta(seconds=entry_ttl_leeway(entry)) < now:
                # Entry is far beyond its TTL, remove it entirely.
                self._data.pop(key, None)
                return None
            return entry

    async def set(self, key: str, entry: CacheEntry, ttl: int) -> None:
        async with self._lock:
            self._data[key] = entry

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def close(self) -> None:  # pragma: no cover - nothing to cleanup
        async with self._lock:
            self._data.clear()


class RedisCacheBackend:
    """Redis powered backend to share cache state across workers."""

    def __init__(self, url: str) -> None:
        if Redis is None:
            raise RuntimeError("redis dependency is not installed")
        if not url:
            raise ValueError("Redis URL must be provided for redis cache backend")
        self._redis = Redis.from_url(url, decode_responses=False)

    async def get(self, key: str) -> CacheEntry | None:
        payload = await self._redis.get(key)
        if payload is None:
            return None
        try:
            entry: CacheEntry = pickle.loads(payload)
        except Exception:  # pragma: no cover - corrupted payload
            logger.exception("Failed to deserialize cache entry for key %s", key)
            await self._redis.delete(key)
            return None
        return entry

    async def set(self, key: str, entry: CacheEntry, ttl: int) -> None:
        payload = pickle.dumps(entry)
        ttl_with_slack = max(ttl * 3, ttl + 300)
        await self._redis.set(key, payload, ex=ttl_with_slack)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.close()


def entry_ttl_leeway(entry: CacheEntry) -> int:
    """Provide additional time-to-live slack for cache eviction checks."""

    ttl = int((entry.expires_at - entry.stored_at).total_seconds())
    return max(ttl, 300)


class TelegramCacheManager:
    """Manage cache backend instantiation based on dynamic configuration."""

    def __init__(self) -> None:
        self._backend: CacheBackend | None = None
        self._config: config_registry.TelegramCacheConfig | None = None
        self._lock = asyncio.Lock()

    async def _ensure_backend(self) -> tuple[CacheBackend, config_registry.TelegramCacheConfig]:
        config = await config_registry.get_telegram_cache_config()
        async with self._lock:
            if self._backend is not None and self._config == config:
                return self._backend, config

            if self._backend is not None:
                try:
                    await self._backend.close()
                except Exception:  # pragma: no cover - best effort cleanup
                    logger.exception("Failed to close previous cache backend")

            backend = await self._build_backend(config)
            self._backend = backend
            self._config = config
            return backend, config

    async def _build_backend(self, config: config_registry.TelegramCacheConfig) -> CacheBackend:
        backend_name = config.backend
        if backend_name == "redis":
            try:
                return RedisCacheBackend(config.redis_url or "")
            except Exception as exc:
                logger.warning(
                    "Falling back to in-memory cache backend because Redis backend failed: %s",
                    exc,
                )
        return InMemoryCacheBackend()

    async def reset(self) -> None:
        async with self._lock:
            if self._backend is not None:
                try:
                    await self._backend.close()
                except Exception:  # pragma: no cover - best effort cleanup
                    logger.exception("Failed to close cache backend during reset")
            self._backend = None
            self._config = None

    async def get_backend(self) -> tuple[CacheBackend, config_registry.TelegramCacheConfig]:
        return await self._ensure_backend()


telegram_cache_manager = TelegramCacheManager()


def _build_admin_cache_key(chat_id: int) -> str:
    return f"telegram:chat:{chat_id}:admins"


async def get_cached_admin_ids(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> list[int] | None:
    """Return administrator IDs using the configured cache backend."""

    bot: Bot | None = context.bot
    if bot is None:
        logger.debug("Telegram context bot missing while resolving admin cache")
        return None

    backend, config = await telegram_cache_manager.get_backend()

    key = _build_admin_cache_key(chat_id)
    entry = await backend.get(key)
    now = datetime.now(timezone.utc)

    if entry and entry.is_valid(now=now):
        return list(entry.value)

    try:
        admins = await bot.get_chat_administrators(chat_id)
    except TelegramError as exc:
        if entry:
            logger.debug(
                "Using stale cached admin list for chat %s due to Telegram error: %s",
                chat_id,
                exc,
            )
            return list(entry.value)
        logger.warning("Failed to fetch administrators for chat %s: %s", chat_id, exc)
        return None

    admin_ids = [member.user.id for member in admins if member.user]

    ttl_seconds = max(config.ttl_seconds, 30)
    expires_at = now + timedelta(seconds=ttl_seconds)
    new_entry = CacheEntry(value=admin_ids, expires_at=expires_at, stored_at=now)
    await backend.set(key, new_entry, ttl_seconds)

    return admin_ids


async def invalidate_chat_admins(chat_id: int) -> None:
    """Invalidate cached administrator IDs for the specified chat."""

    backend, _ = await telegram_cache_manager.get_backend()
    await backend.delete(_build_admin_cache_key(chat_id))
