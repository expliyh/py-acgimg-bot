"""Configuration endpoints exposing feature toggles for the admin console."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from registries import config_registry

router = APIRouter(prefix="/api/config", tags=["config"])


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

    mutable_keys = {"allow_r18g", "enable_on_new_group"}
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
