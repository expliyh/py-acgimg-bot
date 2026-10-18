"""Configuration endpoints exposing feature toggles for the admin console."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from configs import db_config_declare
from registries import config_registry
from services.storage_service.config_defaults import STORAGE_CONFIG_DEFAULTS

router = APIRouter(prefix="/api/config", tags=["config"])

ConfigText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4096)]
ConfigSecret = Annotated[str, StringConstraints(max_length=4096)]


class StorageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_service_use: Literal["local", "backblaze", "webdav", "disabled"] = "local"
    local_storage_root: ConfigText = "storage"
    local_storage_base_url: ConfigText = ""
    backblaze_app_id: ConfigText = ""
    backblaze_app_key: ConfigSecret = ""
    backblaze_bucket_name: ConfigText = ""
    backblaze_base_path: ConfigText = ""
    backblaze_base_url: ConfigText = ""
    webdav_endpoint: ConfigText = ""
    webdav_username: ConfigText = ""
    webdav_password: ConfigSecret = ""
    webdav_base_path: ConfigText = ""
    webdav_public_url: ConfigText = ""

    @field_validator(
        "local_storage_base_url", "backblaze_base_url", "webdav_endpoint", "webdav_public_url"
    )
    @classmethod
    def http_url(cls, value: str) -> str:
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("请填写有效的 HTTP(S) 地址")
        return value.rstrip("/")


class StorageSettingsUpdate(StorageSettings):
    @model_validator(mode="after")
    def active_provider(self):
        if self.storage_service_use == "webdav" and not self.webdav_endpoint:
            raise ValueError("使用 WebDAV 时必须填写服务地址")
        if self.storage_service_use == "backblaze" and not all((
            self.backblaze_app_id, self.backblaze_app_key,
            self.backblaze_bucket_name, self.backblaze_base_url,
        )):
            raise ValueError("使用 Backblaze B2 时必须填写 Key ID、Key、存储桶和公开访问地址")
        return self


class CacheSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["memory", "redis"] = "memory"
    ttl_seconds: int = Field(300, ge=30, le=2147483647)
    redis_url: ConfigText = ""


class CacheSettingsUpdate(CacheSettings):
    @model_validator(mode="after")
    def redis_address(self):
        if self.redis_url:
            parsed = urlparse(self.redis_url)
            if not (
                parsed.scheme in {"redis", "rediss"} and parsed.hostname
                or parsed.scheme == "unix" and parsed.path.startswith("/")
            ):
                raise ValueError("请填写有效的 Redis 地址")
        if self.backend == "redis" and not self.redis_url:
            raise ValueError("使用 Redis 缓存时必须填写连接地址")
        return self


class AccessSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    super_user: ConfigText = str(db_config_declare["super_user"])

    @field_validator("super_user")
    @classmethod
    def user_ids(cls, value: str) -> str:
        ids = re.split(r"[\s,，]+", value.strip()) if value.strip() else []
        if any(not item.isascii() or not item.isdigit() or not 0 < int(item) <= 9007199254740991 for item in ids):
            raise ValueError("超级管理员 ID 必须是正整数，请使用逗号或换行分隔")
        return ",".join(dict.fromkeys(str(int(item)) for item in ids))


@router.get("/storage", response_model=StorageSettings)
async def get_storage_settings():
    values = {}
    for key, default in STORAGE_CONFIG_DEFAULTS.items():
        value = await config_registry.get_config(key)
        values[key] = default if value is None else value
    if str(values["storage_service_use"]).lower() in {"none", ""}:
        values["storage_service_use"] = "disabled"
    return values


@router.put("/storage", response_model=StorageSettings)
async def save_storage_settings(payload: StorageSettingsUpdate):
    from services import storage_service
    from services.file_service.get_file import reset_local_storage_root

    await config_registry.update_configs(payload.model_dump())
    for provider in (storage_service.local_storage, storage_service.backblaze, storage_service.webdav_storage):
        await provider.invalidate_config()
    reset_local_storage_root()
    return payload


@router.get("/cache", response_model=CacheSettings)
async def get_cache_settings():
    value = asdict(await config_registry.get_telegram_cache_config())
    value["redis_url"] = value["redis_url"] or ""
    # Historical Telegram settings may select Redis before its URL is supplied.
    # Keep that configuration readable so the admin can repair it in the form.
    return value


@router.put("/cache", response_model=CacheSettings)
async def save_cache_settings(payload: CacheSettingsUpdate):
    from services.telegram_cache import telegram_cache_manager

    await config_registry.update_configs({
        "telegram_cache_backend": payload.backend,
        "telegram_cache_ttl_seconds": str(payload.ttl_seconds),
        "telegram_cache_redis_url": payload.redis_url,
    })
    await telegram_cache_manager.reset()
    return payload


@router.get("/access", response_model=AccessSettings)
async def get_access_settings():
    value = await config_registry.get_config("super_user")
    return {"super_user": db_config_declare["super_user"] if value is None else value}


@router.put("/access", response_model=AccessSettings)
async def save_access_settings(payload: AccessSettings):
    await config_registry.update_configs(payload.model_dump())
    return payload


class FeatureFlag(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    description: str
    value: bool | None
    editable: bool
    category: str


class FeatureFlagUpdate(BaseModel):
    value: bool


class FeatureFlagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    features: list[FeatureFlag]
    placeholders: list[FeatureFlag]


async def _get_bool_config(key: str, default: bool | None = None) -> bool | None:
    value = await config_registry.get_config(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default


@router.get("/features", response_model=FeatureFlagResponse)
async def get_feature_flags() -> FeatureFlagResponse:
    """Return active feature flags and placeholder configuration entries."""

    feature_definitions: list[dict[str, Any]] = [
        {
            "key": "allow_r18g",
            "label": "允许 R18G",
            "description": "控制全局是否允许在内容推荐中出现 R18G 资源。",
            "default": False,
            "category": "内容安全",
            "editable": True,
        },
        {
            "key": "enable_on_new_group",
            "label": "新群自动启用",
            "description": "当新的群组加入时是否默认启用全部功能。",
            "default": False,
            "category": "群组管理",
            "editable": True,
        },
        {
            "key": "pixiv_cache_to_telegram",
            "label": "导入时缓存 Pixiv 文件",
            "description": "控制导入 Pixiv 插画时是否预先向 Telegram 缓存文件 ID；关闭后将在首次发送时缓存。",
            "default": True,
            "category": "Pixiv",
            "editable": True,
        },
    ]

    features: list[FeatureFlag] = []
    for definition in feature_definitions:
        value = await _get_bool_config(definition["key"], definition["default"])
        features.append(
            FeatureFlag(
                key=definition["key"],
                label=definition["label"],
                description=definition["description"],
                value=value,
                editable=definition["editable"],
                category=definition["category"],
            )
        )

    placeholders: list[FeatureFlag] = [
        FeatureFlag(
            key="setu_moderation",
            label="涩图内容控制",
            description="已在群组配置中细化管理，这里预留用于未来的全局策略。",
            value=None,
            editable=False,
            category="内容安全",
        ),
        FeatureFlag(
            key="content_moderation_pipeline",
            label="智能审核",
            description="计划接入第三方审核服务，用于自动拦截违规内容。",
            value=None,
            editable=False,
            category="实验功能",
        ),
        FeatureFlag(
            key="analytics_stream",
            label="实时统计",
            description="用于展示实时消息趋势的功能占位。",
            value=None,
            editable=False,
            category="数据洞察",
        ),
    ]

    return FeatureFlagResponse(features=features, placeholders=placeholders)


@router.put("/features/{key}", response_model=FeatureFlag)
async def update_feature_flag(key: str, payload: FeatureFlagUpdate) -> FeatureFlag:
    """Update a mutable feature flag value."""

    mutable_keys = {"allow_r18g", "enable_on_new_group", "pixiv_cache_to_telegram"}
    if key not in mutable_keys:
        raise HTTPException(status_code=404, detail="Feature flag not found or not editable")

    await config_registry.update_config(key, payload.value)

    value = await _get_bool_config(key, payload.value)
    labels = {
        "allow_r18g": ("允许 R18G", "控制全局是否允许在内容推荐中出现 R18G 资源。", "内容安全"),
        "enable_on_new_group": (
            "新群自动启用",
            "当新的群组加入时是否默认启用全部功能。",
            "群组管理",
        ),
        "pixiv_cache_to_telegram": (
            "导入时缓存 Pixiv 文件",
            "控制导入阶段是否预缓存 Telegram 文件 ID；关闭后将在首次发送时缓存。",
            "Pixiv",
        ),
    }
    label, description, category = labels[key]

    return FeatureFlag(
        key=key,
        label=label,
        description=description,
        value=value,
        editable=True,
        category=category,
    )
