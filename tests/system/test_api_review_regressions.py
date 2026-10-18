"""Regression coverage for configuration persistence and request validation."""

from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text

from defines import GroupChatMode, UserStatus
from models import Group, User
from registries import engine


@pytest.fixture
async def review_api():
    import main

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.parametrize(
    ("model", "url", "field", "value"),
    [
        (Group, "/api/groups/1", "chat_mode", GroupChatMode.MIXED),
        (User, "/api/private/users/1", "status", UserStatus.BLOCKED),
    ],
)
async def test_patch_enum_round_trip_keeps_database_names(review_api, model, url, field, value):
    async with engine.new_session() as session:
        session.add(model(id=1))
        await session.commit()

    response = await review_api.patch(url, json={field: value.value})
    assert response.status_code == 200, response.text
    assert response.json()[field] == value.value
    assert (await review_api.get(url)).json()[field] == value.value
    async with engine.new_session() as session:
        stored = await session.get(model, 1)
        assert getattr(stored, field) is value
        raw = await session.scalar(text(f"SELECT {field} FROM {model.__tablename__} WHERE id = 1"))
        assert raw == value.name


@pytest.mark.parametrize(
    ("url", "field"),
    [("/api/groups/1", field) for field in (
        "enable", "enable_chat", "chat_mode", "sanity_limit", "allow_r18g", "allow_setu", "admin_ids",
    )] + [("/api/private/users/1", field) for field in (
        "enable_chat", "sanity_limit", "allow_r18g", "status",
    )],
)
async def test_patch_required_fields_reject_explicit_null(review_api, url, field):
    response = await review_api.patch(url, json={field: None})
    assert response.status_code == 422, response.text
    assert field in response.json()["error"]["fields"]


@pytest.mark.parametrize(
    ("model", "url", "field"),
    [(Group, "/api/groups/1", "name"), (User, "/api/private/users/1", "nick_name")],
)
async def test_patch_empty_payload_and_clear_nullable_name(review_api, model, url, field):
    async with engine.new_session() as session:
        session.add(model(id=1, **{field: "before"}))
        await session.commit()
    assert (await review_api.patch(url, json={})).json()[field] == "before"
    response = await review_api.patch(url, json={field: None})
    assert response.status_code == 200, response.text
    assert response.json()[field] is None


@pytest.mark.parametrize("limit", [-1, 0, 101])
async def test_dashboard_rejects_invalid_limit(review_api, limit):
    assert (await review_api.get(f"/api/dashboard/summary?limit={limit}")).status_code == 422


@pytest.mark.parametrize(
    "patch",
    [{"mode": "fixed_different"}, {"group_ids": []}, {"target_scope": "all"}, {"pid": None}],
)
async def test_plan_patch_invalid_merged_config_is_422(review_api, monkeypatch, patch):
    from types import SimpleNamespace
    from routers import image_push

    current = SimpleNamespace(
        target_scope="selected", group_ids=[1], mode="fixed_same", pid="123", pid_by_group=None,
    )
    monkeypatch.setattr(image_push.image_push, "get_plan", AsyncMock(return_value=current))
    save = AsyncMock()
    monkeypatch.setattr(image_push.image_push, "update_plan", save)
    response = await review_api.patch("/api/image-push/plans/test", json=patch)
    assert response.status_code == 422, response.text
    save.assert_not_awaited()
