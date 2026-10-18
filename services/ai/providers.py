"""One provider catalogue, shared selection validation and runtime resolution."""

import asyncio
import json
import uuid
import weakref
from contextlib import asynccontextmanager

from sqlalchemy import select

from models import Config, GroupGuardSettings, GuardRecord
from registries import engine
from .schemas import AIRequestConfig, AISelection, Provider, ProviderInput, PublicProvider

CATALOGUE_KEY = "ai_providers"
SELECTION_FIELDS = ("ai_text", "ai_vision", "ai_username")
_locks = weakref.WeakKeyDictionary()


@asynccontextmanager
async def configuration_lock():
    loop = asyncio.get_running_loop()
    lock = _locks.setdefault(loop, asyncio.Lock())
    async with lock:
        yield


async def all_providers() -> list[Provider]:
    async with engine.new_session() as session:
        row = await session.get(Config, CATALOGUE_KEY)
        return [Provider.model_validate(item) for item in json.loads(row.value_str)] if row else []


def public(provider: Provider) -> PublicProvider:
    return PublicProvider(**provider.model_dump(exclude={"api_key"}), has_api_key=bool(provider.api_key))


async def validate_selection(selection: AISelection | None, catalogue=None, *, feature=None):
    if selection is None:
        return
    catalogue = await all_providers() if catalogue is None else catalogue
    provider = next((p for p in catalogue if p.id == selection.provider_id), None)
    model = next((m for m in provider.models if m.id == selection.model), None) if provider else None
    if model is None:
        raise ValueError("请选择已配置的 AI 提供商和模型")
    required = {"text", "image"} if feature == "ai_vision" else {"text"}
    if feature and (not required.issubset(model.input_types) or "text" not in model.output_types):
        raise ValueError("所选模型不支持此功能所需的输入类型或文本输出")


async def resolve(selection: AISelection | None, catalogue=None) -> AIRequestConfig | None:
    if selection is None:
        return None
    catalogue = await all_providers() if catalogue is None else catalogue
    provider = next((p for p in catalogue if p.id == selection.provider_id), None)
    # A stale selection must never silently use another provider or model.
    model = next((m for m in provider.models if m.id == selection.model), None) if provider else None
    if model is None:
        return None
    return AIRequestConfig(
        provider_id=provider.id, base_url=provider.base_url, api_key=provider.api_key,
        model=selection.model, timeout=provider.timeout, concurrency=provider.concurrency,
        max_input_tokens=model.max_input_tokens, max_output_tokens=model.max_output_tokens,
        input_types=tuple(model.input_types), output_types=tuple(model.output_types),
    )


async def _check_references(catalogue):
    async with engine.new_session() as session:
        defaults = await session.scalar(select(GuardRecord).where(
            GuardRecord.group_id == 0, GuardRecord.kind == "ai_config", GuardRecord.key == "default",
        ))
        configs = [("全局审核服务", defaults.data)] if defaults else []
        groups = (await session.scalars(select(GroupGuardSettings))).all()
        configs.extend((f"群组 {row.group_id}", row.policy or {}) for row in groups)
    for source, config in configs:
        for key in SELECTION_FIELDS:
            if config.get(key):
                try:
                    await validate_selection(AISelection.model_validate(config[key]), catalogue, feature=key)
                except ValueError as exc:
                    raise ValueError(f"{source}仍在使用该提供商或模型，请先修改功能配置") from exc


async def _write(catalogue):
    value = json.dumps([p.model_dump() for p in catalogue], ensure_ascii=False)
    if len(value.encode("utf-8")) > 60000:
        raise ValueError("提供商配置总大小不能超过 60 KB")
    async with engine.new_session() as session:
        await session.merge(Config(key=CATALOGUE_KEY, value_str=value))
        await session.commit()


async def save(payload: ProviderInput, provider_id: str | None = None) -> PublicProvider:
    async with configuration_lock():
        catalogue = await all_providers()
        previous = next((p for p in catalogue if p.id == provider_id), None)
        if provider_id and previous is None:
            raise LookupError("AI 提供商不存在")
        if previous is None and len(catalogue) >= 50:
            raise ValueError("最多添加 50 个 AI 提供商")
        provider = Provider(
            **(payload.model_dump() | {"api_key": previous.api_key if previous and payload.api_key is None else payload.api_key}),
            id=provider_id or uuid.uuid4().hex,
        )
        updated = [provider if p.id == provider.id else p for p in catalogue] if previous else [*catalogue, provider]
        await _check_references(updated)
        await _write(updated)
        return public(provider)


async def remove(provider_id: str):
    async with configuration_lock():
        catalogue = await all_providers()
        updated = [p for p in catalogue if p.id != provider_id]
        if len(updated) == len(catalogue):
            raise LookupError("AI 提供商不存在")
        await _check_references(updated)
        await _write(updated)


async def migrate_legacy_config():
    """Move the previous single-provider config once, without a legacy API path."""
    async with engine.new_session() as session:
        row = await session.scalar(select(GuardRecord).where(
            GuardRecord.group_id == 0, GuardRecord.kind == "ai_config", GuardRecord.key == "default",
        ))
        if row is None or "base_url" not in row.data:
            return
        previous = row.data
        selections = dict.fromkeys(SELECTION_FIELDS)
        if previous.get("base_url"):
            catalogue_row = await session.get(Config, CATALOGUE_KEY)
            catalogue = json.loads(catalogue_row.value_str) if catalogue_row else []
            provider_id = uuid.uuid4().hex
            models = list(dict.fromkeys(filter(None, [previous.get("text_model"), previous.get("vision_model")])))
            provider = Provider(
                id=provider_id, name="原审核服务", base_url=previous["base_url"],
                api_key=previous.get("api_key"), models=models,
                timeout=previous.get("timeout", 20), concurrency=previous.get("concurrency", 2),
            )
            catalogue.append(provider.model_dump())
            await session.merge(Config(key=CATALOGUE_KEY, value_str=json.dumps(catalogue)))
            for field, model in zip(SELECTION_FIELDS, [previous.get("text_model"), previous.get("vision_model"), previous.get("text_model")]):
                if model:
                    selections[field] = {"provider_id": provider_id, "model": model}
        row.data = selections
        await session.commit()
