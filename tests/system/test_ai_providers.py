import asyncio

import httpx
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastapi import FastAPI

from models import Group
from registries import engine
from routers.ai_providers import router
from routers.group_guard import model_router, router as guard_router
from services.ai import providers
from services.ai.client import complete
from services.ai.schemas import AISelection, ProviderInput
from services.moderation import store
from services.moderation.schemas import AIConfig, Policy


def models(*ids):
    return [{"id": value, "input_types": ["text", "image"]} for value in ids]


@pytest.fixture
async def api():
    app = FastAPI()
    for item in (router, model_router, guard_router):
        app.include_router(item)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def add_provider(name="Provider", **values):
    values = {"name": name, "base_url": "http://127.0.0.1:9/v1", "models": ["text", "vision"], "api_key": "test-secret"} | values
    values["models"] = models(*values["models"])
    return await providers.save(ProviderInput(
        **values
    ))


async def test_catalogue_crud_normalizes_models_and_hides_keys(api):
    payload = {"name": "A", "base_url": "https://example.test/v1/", "api_key": "secret-value", "models": models(" text ", "vision")}
    created = await api.post("/api/ai/providers", json=payload)
    assert created.status_code == 201
    item = created.json()
    assert [m["id"] for m in item["models"]] == ["text", "vision"] and item["base_url"].endswith("/v1")
    assert item["has_api_key"] and "secret-value" not in created.text and "api_key" not in item
    second = await api.post("/api/ai/providers", json=payload | {"name": "B"})
    assert second.json()["id"] != item["id"]
    listed = await api.get("/api/ai/providers")
    assert len(listed.json()) == 2 and "secret-value" not in listed.text
    endpoint = "/api/ai/providers/" + item["id"]
    for key in (None, ""):
        changed = await api.put(endpoint, json=payload | {"api_key": key})
        assert changed.status_code == 200 and changed.json()["has_api_key"] == (key is None)
    assert (await api.delete(endpoint)).status_code == 200
    assert (await api.delete(endpoint)).status_code == 404
    assert (await api.put(endpoint, json=payload)).status_code == 404


@pytest.mark.parametrize("invalid", [
    {"models": [{"id": " "}]}, {"name": " "},
    {"models": models("duplicate", "duplicate")}, {"models": ["old-format"]},
    {"models": [{"id": "test", "max_input_tokens": 0}]},
    {"models": [{"id": "test", "max_output_tokens": -1}]},
    {"models": [{"id": "test", "max_input_tokens": 1.5}]},
    {"models": [{"id": "test", "input_types": []}]},
    {"models": [{"id": "test", "output_types": ["unknown"]}]},
    {"base_url": "https://user:secret@example.test/v1"}, {"base_url": "bad-url"},
    {"base_url": "https://example.test/v1?api_key=secret"},
    {"concurrency": 0}, {"timeout": 121},
])
async def test_invalid_provider_is_not_saved(api, invalid):
    response = await api.post("/api/ai/providers", json={
        "name": "Provider", "base_url": "http://localhost/v1", "models": models("test"), **invalid,
    })
    assert response.status_code == 422
    assert await providers.all_providers() == []


async def test_features_select_independently_and_null_restores_inheritance(api):
    text = await add_provider("Text")
    vision = await add_provider("Vision", base_url="http://127.0.0.1:8/v1")
    default = AISelection(provider_id=text.id, model="text")
    own = AISelection(provider_id=vision.id, model="vision")
    await store.save_ai_config(AIConfig(ai_text=default, ai_username=default))
    async with engine.new_session() as session:
        session.add_all([Group(id=-1001), Group(id=-1002)])
        await session.commit()
    response = await api.patch("/api/groups/-1001/guard", json={"ai_text": own.model_dump(), "ai_vision": own.model_dump()})
    assert response.status_code == 200
    first, second = await store.policy(-1001), await store.policy(-1002)
    assert (await store.resolve_ai(first, "ai_text")).provider_id == vision.id
    assert (await store.resolve_ai(second, "ai_text")).provider_id == text.id
    assert (await store.resolve_ai(first, "ai_username")).model == "text"
    assert await store.resolve_ai(second, "ai_vision") is None
    response = await api.patch("/api/groups/-1001/guard", json={"ai_text": None})
    assert response.status_code == 200
    assert (await store.resolve_ai(await store.policy(-1001), "ai_text")).provider_id == text.id
    invalid = {"provider_id": vision.id, "model": "missing"}
    assert (await api.put("/api/guard-ai", json={"ai_text": invalid})).status_code == 422
    assert (await api.patch("/api/groups/-1001/guard", json={"ai_text": invalid})).status_code == 422
    assert (await store.ai_config()).ai_text == default
    assert (await store.policy(-1001)).ai_text is None


async def test_referenced_providers_and_models_require_unbinding(api):
    item = await add_provider()
    selection = AISelection(provider_id=item.id, model="vision")
    await store.save_ai_config(AIConfig(ai_vision=selection))
    endpoint = "/api/ai/providers/" + item.id
    assert (await api.delete(endpoint)).status_code == 409
    payload = {"name": "New", "base_url": "http://localhost/v1", "models": models("text")}
    assert (await api.put(endpoint, json=payload)).status_code == 422
    await store.save_ai_config(AIConfig())
    await store.save_policy(-1001, {"ai_username": selection.model_dump()})
    assert (await api.delete(endpoint)).status_code == 409
    # Removing an unused model and rotating a key is allowed while a model is bound.
    response = await api.put(endpoint, json=payload | {"models": models("vision"), "api_key": "rotated"})
    assert response.status_code == 200
    resolved = await store.resolve_ai(await store.policy(-1001), "ai_username")
    assert resolved.api_key == "rotated" and resolved.base_url == "http://localhost/v1"
    await store.save_policy(-1001, {"ai_username": None})
    assert (await api.delete(endpoint)).status_code == 200
    assert await providers.resolve(selection) is None


async def test_legacy_config_migrates_once_and_preserves_other_providers():
    existing = await add_provider("Existing")
    await store.put_record(0, "ai_config", "default", {
        "base_url": "https://old.example/v1", "api_key": "old-key",
        "text_model": "text-old", "vision_model": "vision-old", "timeout": 30, "concurrency": 3,
    })
    await providers.migrate_legacy_config()
    await providers.migrate_legacy_config()
    catalogue = await providers.all_providers()
    assert len(catalogue) == 2 and catalogue[0].id == existing.id
    config = await store.ai_config()
    assert config.ai_text == config.ai_username and config.ai_vision.model == "vision-old"
    resolved = await store.resolve_ai(Policy(), "ai_text")
    assert resolved.api_key == "old-key" and resolved.timeout == 30 and resolved.concurrency == 3
    persisted = (await store.record(0, "ai_config", "default"))["data"]
    assert "base_url" not in persisted and "api_key" not in persisted


async def test_provider_without_models_preserves_credentials_during_migration(api):
    created = await api.post("/api/ai/providers", json={
        "name": "Draft", "base_url": "https://draft.example/v1", "models": [],
    })
    assert created.status_code == 201 and created.json()["models"] == []
    await store.put_record(0, "ai_config", "default", {
        "base_url": "https://old.example/v1", "api_key": "keep-me", "text_model": "", "vision_model": "",
    })
    await providers.migrate_legacy_config()
    migrated = (await providers.all_providers())[1]
    assert migrated.models == [] and migrated.api_key == "keep-me"
    assert (await store.ai_config()) == AIConfig()


async def test_requests_use_selected_provider_model_and_independent_limits():
    seen = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def respond(request):
        body = await request.json()
        seen.append((request.headers.get("Authorization"), body["model"]))
        if body["model"] == "slow":
            entered.set()
            await release.wait()
        return web.json_response({"choices": [{"message": {"content": "ok"}}]})

    app = web.Application()
    app.router.add_post("/chat/completions", respond)
    async with TestServer(app) as server:
        first = await add_provider("First", base_url=str(server.make_url("/")), models=["slow"], api_key="first", concurrency=1)
        second = await add_provider("Second", base_url=str(server.make_url("/")), models=["fast"], api_key="second", concurrency=1)
        slow = await providers.resolve(AISelection(provider_id=first.id, model="slow"))
        fast = await providers.resolve(AISelection(provider_id=second.id, model="fast"))
        job = asyncio.create_task(complete(slow, []))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert await asyncio.wait_for(complete(fast, []), 2) == ("ok", {})
        finally:
            release.set()
            await job
    assert seen == [("Bearer first", "slow"), ("Bearer second", "fast")]


async def test_model_capabilities_round_trip_and_guard_feature_validation(api):
    payload = {"name": "Capabilities", "base_url": "http://localhost/v1", "models": [
        {"id": "text", "max_input_tokens": 32000, "max_output_tokens": 2048,
         "input_types": ["text"], "output_types": ["text"]},
        {"id": "vision", "max_input_tokens": 128000, "max_output_tokens": 4096,
         "input_types": ["text", "image"], "output_types": ["text"]},
        {"id": "media", "input_types": ["text", "audio", "video", "file"], "output_types": ["image", "audio"]},
    ]}
    created = await api.post("/api/ai/providers", json=payload)
    assert created.status_code == 201
    provider_id = created.json()["id"]
    saved = (await api.get("/api/ai/providers")).json()[0]
    assert saved["models"][0] == payload["models"][0]
    text = {"provider_id": provider_id, "model": "text"}
    vision = {"provider_id": provider_id, "model": "vision"}
    media = {"provider_id": provider_id, "model": "media"}
    assert (await api.put("/api/guard-ai", json={"ai_vision": text})).status_code == 422
    assert (await api.put("/api/guard-ai", json={"ai_text": media})).status_code == 422
    assert (await api.put("/api/guard-ai", json={"ai_text": text, "ai_vision": vision})).status_code == 200
    config = await providers.resolve(AISelection(**text))
    assert config.max_input_tokens == 32000 and config.max_output_tokens == 2048
    assert config.input_types == ("text",) and config.output_types == ("text",)
    payload["models"][1]["input_types"] = ["text"]
    assert (await api.put("/api/ai/providers/" + provider_id, json=payload)).status_code == 422
    assert (await providers.all_providers())[0].models[1].input_types == ["text", "image"]
    async with engine.new_session() as session:
        session.add(Group(id=-1001))
        await session.commit()
    assert (await api.patch("/api/groups/-1001/guard", json={"ai_vision": text})).status_code == 422


async def test_existing_saved_model_ids_get_capabilities_without_losing_selections():
    import json
    from models import Config
    async with engine.new_session() as session:
        session.add(Config(key="ai_providers", value_str=json.dumps([{
            "id": "old", "name": "Existing", "base_url": "http://localhost/v1", "models": ["text", "vision"],
        }])))
        await session.commit()
    saved = (await providers.all_providers())[0]
    assert [model.id for model in saved.models] == ["text", "vision"]
    assert saved.models[1].input_types == ["text", "image"]
    assert saved.models[0].max_input_tokens is None
    await store.save_ai_config(AIConfig(ai_vision=AISelection(provider_id="old", model="vision")))
    assert (await store.resolve_ai(Policy(), "ai_vision")).model == "vision"


async def test_requests_apply_output_limit_and_reject_incompatible_input_before_http():
    from dataclasses import replace
    from services.ai.schemas import AIRequestConfig
    seen = []
    async def respond(request):
        seen.append(await request.json())
        return web.json_response({"choices": [{"message": {"content": "ok"}}]})
    app = web.Application()
    app.router.add_post("/chat/completions", respond)
    async with TestServer(app) as server:
        config = AIRequestConfig(provider_id="limits", base_url=str(server.make_url("/")).rstrip("/"),
                                 api_key=None, model="text", max_output_tokens=123, input_types=("text",))
        assert await complete(config, [{"role": "user", "content": "test"}]) == ("ok", {})
        assert seen[0]["max_tokens"] == 123
        with pytest.raises(ValueError, match="输入类型"):
            await complete(config, [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]}])
        with pytest.raises(ValueError, match="文本输出"):
            await complete(replace(config, output_types=("image",)), [])
        assert len(seen) == 1


async def test_input_budget_checks_full_messages_and_media_before_http():
    from dataclasses import replace
    from services.ai.schemas import AIRequestConfig

    seen = []

    async def respond(request):
        seen.append(await request.json())
        return web.json_response({"choices": [{"message": {"content": "ok"}}]})

    app = web.Application()
    app.router.add_post("/chat/completions", respond)
    async with TestServer(app) as server:
        config = AIRequestConfig(provider_id="input-budget", base_url=str(server.make_url("/")).rstrip("/"),
                                 api_key=None, model="text", max_input_tokens=180)
        short = [{"role": "user", "content": "test"}]
        assert await complete(config, short) == ("ok", {})
        assert seen[-1]["messages"] == short
        for messages in (
            [{"role": "user", "content": "a" * 200}],
            [{"role": "user", "content": "中" * 60}],
            [{"role": "system", "content": "policy " * 20}, *short],
            [{"role": "user", "content": [{"type": "text", "text": "a" * 70},
                                           {"type": "text", "text": "b" * 70}]}],
            [{"role": "user", "content": ""}] * 4,
            [{"role": "user", "content": [{"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + "AAAA" * 100}}]}],
        ):
            with pytest.raises(ValueError, match="超过模型输入上限"):
                await complete(config, messages)
        remote_image = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.test/a.png"}}]}]
        with pytest.raises(ValueError, match="无法估算"):
            await complete(config, remote_image)
        audio = [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}}]}]
        with pytest.raises(ValueError, match="无法估算"):
            await complete(replace(config, input_types=("text", "audio")), audio)
        assert len(seen) == 1
        # Unbounded models preserve the existing request behavior.
        await complete(replace(config, max_input_tokens=None), remote_image)
        assert len(seen) == 2 and seen[-1]["messages"] == remote_image
        # Bounded vision requests still work when their inline data fits the estimate.
        inline = [{"role": "user", "content": [{"type": "text", "text": "caption"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
        await complete(replace(config, max_input_tokens=1000), inline)
        assert seen[-1]["messages"] == inline
