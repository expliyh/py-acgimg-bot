from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from models import Config
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
    return [Token(token=i.value_str or "", enable=bool(i.value_bool)) for i in configs]


async def get_pixiv_tokens() -> list[Token]:
    configs = await get_configs("pixiv_token")
    return [Token(token=i.value_str or "", enable=bool(i.value_bool)) for i in configs]


async def set_pixiv_token(token: str | None) -> None:
    normalized = _optional_str(token)
    async with engine.new_session() as session:
        config = await session.get(Config, "pixiv_token")
        if config is None:
            config = Config(key="pixiv_token")
            session.add(config)
        config.value_str = normalized
        await session.commit()


async def set_pixiv_token_enabled(enabled: bool) -> None:
    async with engine.new_session() as session:
        config = await session.get(Config, "pixiv_token")
        if config is None:
            config = Config(key="pixiv_token")
            session.add(config)
        config.value_bool = enabled
        await session.commit()


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
