"""Global configuration persistence, validation and runtime invalidation."""

import importlib
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from registries import config_registry, engine
from routers.configs import router
from services import storage_service, schema_migrator
from services.permissions import has_super_user_access
from services.telegram_cache import telegram_cache_manager


@pytest.fixture
def config_client():
    # Configuration endpoints do not require Telegram startup or external services.
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def test_default_sections_are_available_without_seed_rows(config_client):
    storage = config_client.get("/api/config/storage")
    assert storage.status_code == 200
    assert storage.json()["storage_service_use"] == "local"
    assert storage.json()["local_storage_root"] == "storage"
    assert config_client.get("/api/config/cache").json() == {
        "backend": "memory", "ttl_seconds": 300, "redis_url": "",
    }
    assert config_client.get("/api/config/access").json()["super_user"]


def test_active_storage_provider_requires_complete_configuration(config_client):
    original = config_client.get("/api/config/storage").json()
    for provider in ("webdav", "backblaze", "unknown"):
        response = config_client.put("/api/config/storage", json={**original, "storage_service_use": provider})
        assert response.status_code == 422
    assert config_client.get("/api/config/storage").json() == original


async def test_storage_roundtrip_reloads_all_providers_and_local_resolution(config_client, monkeypatch):
    file_service = importlib.import_module("services.file_service.get_file")
    file_service._LOCAL_STORAGE_ROOT = file_service.Path("old-root")
    providers = (storage_service.local_storage, storage_service.backblaze, storage_service.webdav_storage)
    invalidators = []
    for provider in providers:
        invalidate = AsyncMock()
        invalidators.append(invalidate)
        monkeypatch.setattr(provider, "invalidate_config", invalidate)
    payload = config_client.get("/api/config/storage").json()
    payload.update({
        "storage_service_use": "webdav",
        "webdav_endpoint": "https://storage.example/" + "long-path/" * 12,
        "webdav_password": "test-password",
        "backblaze_app_key": "test-key",
        "local_storage_root": "new-root",
    })
    response = config_client.put("/api/config/storage", json=payload)
    assert response.status_code == 200
    saved = response.json()
    assert saved["webdav_endpoint"] == payload["webdav_endpoint"].rstrip("/")
    assert config_client.get("/api/config/storage").json() == saved
    assert await config_registry.get_config("webdav_password") == "test-password"
    assert file_service._LOCAL_STORAGE_ROOT is None
    for invalidate in invalidators:
        invalidate.assert_awaited_once()
    # Invalid sections are rejected before any field is written.
    response = config_client.put("/api/config/storage", json={**saved, "webdav_endpoint": "bad-url"})
    assert response.status_code == 422
    assert config_client.get("/api/config/storage").json() == saved


def test_cache_save_resets_runtime_and_rejects_invalid_sections(config_client, monkeypatch):
    reset = AsyncMock()
    monkeypatch.setattr(telegram_cache_manager, "reset", reset)
    payload = {"backend": "redis", "ttl_seconds": 600, "redis_url": "redis://localhost:6379/0"}
    response = config_client.put("/api/config/cache", json=payload)
    assert response.status_code == 200
    assert config_client.get("/api/config/cache").json() == payload
    reset.assert_awaited_once()
    for invalid in (
        {**payload, "backend": "unknown"},
        {**payload, "ttl_seconds": 29},
        {**payload, "redis_url": ""},
        {**payload, "redis_url": "http://redis.example"},
    ):
        assert config_client.put("/api/config/cache", json=invalid).status_code == 422
    assert config_client.get("/api/config/cache").json() == payload
    assert reset.await_count == 1


async def test_incomplete_legacy_redis_config_remains_readable(config_client):
    await config_registry.set_telegram_cache_backend("redis")
    response = config_client.get("/api/config/cache")
    assert response.status_code == 200
    assert response.json()["backend"] == "redis"
    assert response.json()["redis_url"] == ""


async def test_admin_ids_roundtrip_normalizes_and_changes_permission_checks(config_client):
    response = config_client.put("/api/config/access", json={"super_user": "123，456\n123"})
    assert response.status_code == 200
    assert response.json() == {"super_user": "123,456"}
    assert await has_super_user_access(123)
    assert not await has_super_user_access(789)
    assert config_client.put("/api/config/access", json={"super_user": "bad-id"}).status_code == 422
    assert config_client.get("/api/config/access").json()["super_user"] == "123,456"
    assert config_client.put("/api/config/access", json={"super_user": ""}).status_code == 200
    assert await has_super_user_access(789)


async def test_config_migration_is_repeatable_and_preserves_long_values():
    from sqlalchemy import text

    await config_registry.update_config("webdav_endpoint", "https://example.test/" + "x" * 200)
    await schema_migrator.ensure_schema_migrations(engine.engine)
    await schema_migrator.ensure_schema_migrations(engine.engine)
    assert len(await config_registry.get_config("webdav_endpoint")) > 200
    async with engine.engine.connect() as connection:
        assert (await connection.scalar(text("SELECT MAX(version) FROM schema_migrations"))) == 9
