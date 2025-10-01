from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import delete, select, update

from models import Config, PixivToken
from .engine import engine


def _optional_str(value: str | bool | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    text = str(value).strip()
    return text or None


@dataclass
class Token:
    token: str
    enable: bool
    id: int | None = None


@dataclass(slots=True)
class TelegramCacheConfig:
    backend: Literal["memory", "redis"] = "memory"
    ttl_seconds: int = 300
    redis_url: str | None = None


@dataclass
class BackBlazeConfig:
    app_id: str | None = None
    app_key: str | None = None
    bucket_name: str | None = None
    base_path: str | None = None
    base_url: str | None = None

    def __post_init__(self) -> None:
        self.base_path = self._normalize_path(self.base_path)
        self.base_url = self._normalize_url(self.base_url)

    @staticmethod
    def _normalize_path(path: str | None) -> str | None:
        cleaned = _optional_str(path)
        if cleaned is None:
            return None
        return cleaned.replace("\\", "/").strip("/") or None

    @staticmethod
    def _normalize_url(url: str | None) -> str | None:
        cleaned = _optional_str(url)
        if cleaned is None:
            return None
        return cleaned.rstrip("/") or None


@dataclass
class WebDavConfig:
    endpoint: str | None = None
    username: str | None = None
    password: str | None = None
    base_path: str | None = None
    public_base_url: str | None = None

    def __post_init__(self) -> None:
        self.endpoint = _optional_str(self.endpoint)
        self.username = _optional_str(self.username)
        self.password = _optional_str(self.password)
        self.base_path = self._normalize_path(self.base_path)
        self.public_base_url = self._normalize_url(self.public_base_url)

    @staticmethod
    def _normalize_path(path: str | None) -> str | None:
        cleaned = _optional_str(path)
        if cleaned is None:
            return None
        return cleaned.replace("\\", "/").strip("/") or None

    @staticmethod
    def _normalize_url(url: str | None) -> str | None:
        cleaned = _optional_str(url)
        if cleaned is None:
            return None
        return cleaned.rstrip("/") or None


@dataclass
class LocalStorageConfig:
    root_path: str | None = None
    base_url: str | None = None

    def __post_init__(self) -> None:
        self.root_path = self._normalize_path(self.root_path)
        self.base_url = self._normalize_url(self.base_url)

    @staticmethod
    def _normalize_path(path: str | None) -> str | None:
        cleaned = _optional_str(path)
        if cleaned is None:
            return None
        return cleaned.replace("\\", "/") or None

    @staticmethod
    def _normalize_url(url: str | None) -> str | None:
        cleaned = _optional_str(url)
        if cleaned is None:
            return None
        return cleaned.rstrip("/") or None


async def add_config(config: Config, default: str | bool) -> None:
    if config.value_str is None:
        config.value_str = default if isinstance(default, str) else None
    if config.value_bool is None:
        config.value_bool = default if isinstance(default, bool) else None

    async with engine.new_session() as session:
        await session.merge(config)
        await session.commit()


async def update_config(key: str, value: str | bool) -> None:
    config = Config(key)
    config.value_str = value if isinstance(value, str) else None
    config.value_bool = value if isinstance(value, bool) else None

    async with engine.new_session() as session:
        await session.merge(config)
        await session.commit()


async def get_configs(key: str) -> list[Config]:
    async with engine.new_session() as session:
        result = await session.execute(select(Config).where(Config.key == key))
        return list(result.scalars())


async def get_config_detail(key: str) -> Config | None:
    async with engine.new_session() as session:
        result = await session.execute(select(Config).where(Config.key == key))
        return result.scalar_one_or_none()


async def get_config(key: str) -> str | bool | None:
    config = await get_config_detail(key)
    if config is None:
        return None
    if config.value_str is not None:
        return config.value_str
    if config.value_bool is not None:
        return config.value_bool
    return None


async def get_bot_tokens() -> list[Token]:
    configs = await get_configs("bot_token")
    return [Token(token=i.value_str or "", enable=bool(i.value_bool), id=None) for i in configs]


async def get_pixiv_tokens() -> list[Token]:
    async with engine.new_session() as session:
        result = await session.execute(select(PixivToken).order_by(PixivToken.id))
        records = list(result.scalars())

        migrated = False
        if not records:
            legacy = await session.get(Config, "pixiv_token")
            if legacy:
                normalized = _optional_str(legacy.value_str)
                enabled = bool(legacy.value_bool)
                if normalized:
                    record = PixivToken(refresh_token=normalized, enabled=enabled)
                    session.add(record)
                    await session.flush()
                    records = [record]
                    migrated = True
                if legacy.value_str is not None or legacy.value_bool is not None:
                    legacy.value_str = None
                    legacy.value_bool = None
                    migrated = True

        if migrated:
            await session.commit()
            result = await session.execute(select(PixivToken).order_by(PixivToken.id))
            records = list(result.scalars())

        return [Token(token=item.refresh_token, enable=bool(item.enabled), id=item.id) for item in records]

async def add_pixiv_token(token: str, *, enabled: bool = True) -> Token:
    normalized = _optional_str(token)
    if not normalized:
        raise ValueError("Pixiv token cannot be empty")

    async with engine.new_session() as session:
        record = PixivToken(refresh_token=normalized, enabled=enabled)
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return Token(token=record.refresh_token, enable=bool(record.enabled), id=record.id)


async def update_pixiv_token(token_id: int, token: str) -> None:
    normalized = _optional_str(token)
    if not normalized:
        raise ValueError("Pixiv token cannot be empty")

    async with engine.new_session() as session:
        record = await session.get(PixivToken, token_id)
        if record is None:
            raise ValueError(f"Pixiv token {token_id} does not exist")
        record.refresh_token = normalized
        await session.commit()


async def set_pixiv_token_enabled(token_id: int, enabled: bool) -> None:
    async with engine.new_session() as session:
        record = await session.get(PixivToken, token_id)
        if record is None:
            raise ValueError(f"Pixiv token {token_id} does not exist")
        record.enabled = enabled
        await session.commit()


async def set_all_pixiv_tokens_enabled(enabled: bool) -> None:
    async with engine.new_session() as session:
        await session.execute(
            update(PixivToken).values(enabled=enabled)
        )
        await session.commit()


async def delete_pixiv_token(token_id: int) -> None:
    async with engine.new_session() as session:
        await session.execute(
            delete(PixivToken).where(PixivToken.id == token_id)
        )
        await session.commit()


async def delete_all_pixiv_tokens() -> None:
    async with engine.new_session() as session:
        await session.execute(delete(PixivToken))
        await session.commit()


def _normalize_cache_backend(value: str | bool | None) -> Literal["memory", "redis"]:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"memory", "redis"}:
            return cast(Literal["memory", "redis"], normalized)
    if value is True:
        return "redis"
    return "memory"


def _coerce_positive_int(value: str | bool | None, *, default: int, minimum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        numeric = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(numeric, minimum)


async def get_telegram_cache_config() -> TelegramCacheConfig:
    backend_value = await get_config("telegram_cache_backend")
    ttl_value = await get_config("telegram_cache_ttl_seconds")
    redis_url_value = await get_config("telegram_cache_redis_url")

    backend = _normalize_cache_backend(backend_value)
    ttl_seconds = _coerce_positive_int(ttl_value, default=300, minimum=30)
    redis_url = _optional_str(redis_url_value)

    return TelegramCacheConfig(backend=backend, ttl_seconds=ttl_seconds, redis_url=redis_url)


async def set_telegram_cache_backend(backend: str) -> None:
    normalized = _optional_str(backend)
    if normalized not in {"memory", "redis"}:
        raise ValueError("缓存后端必须为 'memory' 或 'redis'")
    await update_config("telegram_cache_backend", normalized)


async def set_telegram_cache_ttl(ttl_seconds: int) -> None:
    if ttl_seconds < 30:
        raise ValueError("缓存 TTL 必须至少为 30 秒")
    await update_config("telegram_cache_ttl_seconds", str(ttl_seconds))


async def set_telegram_cache_redis_url(url: str | None) -> None:
    normalized = _optional_str(url)
    await update_config("telegram_cache_redis_url", normalized or "")



async def get_backblaze_config() -> BackBlazeConfig:
    return BackBlazeConfig(
        app_id=_optional_str(await get_config("backblaze_app_id")),
        app_key=_optional_str(await get_config("backblaze_app_key")),
        bucket_name=_optional_str(await get_config("backblaze_bucket_name")),
        base_path=_optional_str(await get_config("backblaze_base_path")),
        base_url=_optional_str(await get_config("backblaze_base_url")),
    )


async def get_webdav_config() -> WebDavConfig:
    return WebDavConfig(
        endpoint=_optional_str(await get_config("webdav_endpoint")),
        username=_optional_str(await get_config("webdav_username")),
        password=_optional_str(await get_config("webdav_password")),
        base_path=_optional_str(await get_config("webdav_base_path")),
        public_base_url=_optional_str(await get_config("webdav_public_url")),
    )


async def get_local_storage_config() -> LocalStorageConfig:
    return LocalStorageConfig(
        root_path=_optional_str(await get_config("local_storage_root")),
        base_url=_optional_str(await get_config("local_storage_base_url")),
    )


async def init_database_config(db_config_declare: dict[str, str | bool]) -> None:
    for key, default in db_config_declare.items():
        existing_config = await get_config_detail(key)
        if existing_config:
            continue
        config = Config(
            key=key,
            value_str=default if isinstance(default, str) else None,
            value_bool=default if isinstance(default, bool) else None,
        )
        await add_config(config, default)
