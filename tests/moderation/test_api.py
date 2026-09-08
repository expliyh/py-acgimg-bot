"""ASGI contracts, real persistence and group isolation for the guard UI."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, update
from telegram.error import BadRequest

from models import Group, GroupGuardSettings, GuardEvent, GuardTask
from registries import engine
from services import group_guard
from services.moderation import reviews, store, verification


@pytest.fixture
async def api(guard_group, guard_bot, monkeypatch):
    import main
    from bot import tg_bot

    monkeypatch.setattr(tg_bot, "tg_bot", guard_bot)
    async with engine.new_session() as session:
        session.add(Group(id=guard_group + 1))
        await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        yield client


async def test_web_policy_write_invalidates_telegram_cache_and_rejects_invalid_merge(
    api, guard_group
):
    root = f"/api/groups/{guard_group}/guard"
    assert not (await group_guard.get_guard_settings(guard_group)).verification_enabled
    response = await api.patch(
        root, json={"verification_enabled": True, "ai_auto_threshold": 0.8}
    )
    assert response.status_code == 200
    assert (await group_guard.get_guard_settings(guard_group)).verification_enabled
    response = await api.patch(root, json={"ai_review_threshold": 0.9})
    assert response.status_code == 422
    policy = (await api.get(root)).json()
    assert policy["ai_auto_threshold"] == 0.8 and policy["ai_review_threshold"] == 0.7
    assert not (await api.get(f"/api/groups/{guard_group + 1}/guard")).json()[
        "verification_enabled"
    ]


@pytest.mark.parametrize("legacy", [False, True])
async def test_blank_verification_prompt_uses_default(
    api, guard_group, guard_bot, guard_message, legacy
):
    root = f"/api/groups/{guard_group}/guard"
    if legacy:
        async with engine.new_session() as session:
            session.add(GroupGuardSettings(
                group_id=guard_group, verification_message=" \t\n ",
                verification_enabled=True,
            ))
            await session.commit()
    else:
        response = await api.patch(root, json={
            "verification_message": " \t\n ", "verification_enabled": True,
        })
        assert response.status_code == 200
        assert response.json()["verification_message"] is None
    assert (await api.get(root)).json()["verification_message"] is None
    message = guard_message()
    await verification.joined(guard_bot, message.chat, message.from_user)
    assert "请在" in guard_bot.send_message.call_args.args[1]


async def test_action_retries_are_idempotent_and_logged_as_deployment_admin(
    api, guard_group
):
    root = f"/api/groups/{guard_group}/guard"
    request = {
        "action": "warn",
        "user_id": 2,
        "reason": "spam",
        "request_id": "web-retry",
    }
    first = await api.post(root + "/actions", json=request)
    second = await api.post(root + "/actions", json=request)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    warnings = (await api.get(root + "/members/2")).json()["warnings"]
    assert len(warnings) == 1
    assert warnings[0]["source"] == "web:deployment-admin"
    assert (await api.get(f"/api/groups/{guard_group + 1}/guard/members/2")).json()[
        "warnings"
    ] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "warn", "request_id": "missing-target"},
        {
            "action": "purge",
            "message_id": 10,
            "end_message_id": 110,
            "request_id": "too-many",
        },
        {
            "action": "mute",
            "user_id": 2,
            "duration": 0,
            "request_id": "invalid-duration",
        },
    ],
)
async def test_invalid_actions_are_rejected_before_side_effects(
    api, guard_group, guard_bot, payload
):
    response = await api.post(f"/api/groups/{guard_group}/guard/actions", json=payload)
    assert response.status_code == 422
    assert await store.warnings(guard_group, 2) == []
    guard_bot.restrict_chat_member.assert_not_awaited()
    guard_bot.delete_message.assert_not_awaited()


async def test_api_reports_telegram_failure_and_disconnected_bot(
    api, guard_group, guard_bot, monkeypatch
):
    from bot import tg_bot

    root = f"/api/groups/{guard_group}/guard"
    guard_bot.delete_message.side_effect = BadRequest("secret provider details")
    response = await api.post(
        root + "/actions",
        json={"action": "delete", "message_id": 10, "request_id": "failed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "secret provider details" not in response.text
    monkeypatch.setattr(tg_bot, "tg_bot", None)
    response = await api.post(
        root + "/actions",
        json={"action": "warn", "user_id": 2, "request_id": "offline"},
    )
    assert response.status_code == 409
    assert await store.warnings(guard_group, 2) == []


async def test_same_rule_name_and_review_ids_remain_group_scoped(
    api, guard_group, guard_bot
):
    root, other = (f"/api/groups/{gid}/guard" for gid in [guard_group, guard_group + 1])
    for path, keyword in [(root, "spam"), (other, "different")]:
        assert (
            await api.put(
                path + "/rules/shared", json={"kind": "keyword", "pattern": keyword}
            )
        ).status_code == 200
    assert (await api.delete(root + "/rules/shared")).json()["removed"]
    assert (await api.get(other + "/rules")).json()["items"][0]["data"][
        "pattern"
    ] == "different"
    review = await reviews.create(
        guard_group, "report:10", {"kind": "message", "message_id": 10, "user_id": 2}
    )
    response = await api.post(
        other + f"/reviews/{review['id']}", json={"decision": "punish"}
    )
    assert response.status_code == 400
    assert (await store.record(guard_group, "review", "report:10"))["data"][
        "state"
    ] == "pending"
    guard_bot.delete_message.assert_not_awaited()


async def test_logs_pagination_filters_and_stats_only_count_current_group_and_period(
    api, guard_group
):
    root = f"/api/groups/{guard_group}/guard"
    for index in range(3):
        await store.event(
            guard_group,
            "ai",
            status="failed",
            user_id=2,
            data={"usage": {"total_tokens": index + 1}},
        )
    await store.event(guard_group, "warn", user_id=3)
    await store.event(guard_group + 1, "ai", data={"usage": {"total_tokens": 900}})
    old, _ = await store.event(guard_group, "ai", data={"usage": {"total_tokens": 800}})
    async with engine.new_session() as session:
        await session.execute(
            update(GuardEvent)
            .where(GuardEvent.id == old["id"])
            .values(created_at=store.now() - timedelta(days=31))
        )
        await session.commit()
    params = {"status": "failed", "user_id": 2, "page_size": 2}
    first = (await api.get(root + "/logs", params=params)).json()
    second = (await api.get(root + "/logs", params=params | {"page": 2})).json()
    assert first["total"] == 3 and first["pages"] == 2
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert {row["id"] for row in first["items"]}.isdisjoint(
        row["id"] for row in second["items"]
    )
    assert (await api.get(root + "/logs", params={"page_size": 101})).status_code == 422
    stats = (await api.get(root + "/stats")).json()
    assert stats["total_tokens"] == 6
    assert stats["actions"] == {"ai": 3, "warn": 1}
    assert stats["statuses"] == {"failed": 3, "success": 1}


async def test_announcement_input_requires_offset_and_persists_utc(api, guard_group):
    root = f"/api/groups/{guard_group}/guard"
    payload = {
        "kind": "announcement",
        "name": "daily",
        "text": "hello",
        "due_at": "2026-09-08T09:00:00",
    }
    assert (await api.put(root + "/contents", json=payload)).status_code == 422
    payload["due_at"] += "+08:00"
    assert (await api.put(root + "/contents", json=payload)).status_code == 200
    async with engine.new_session() as session:
        task = await session.scalar(
            select(GuardTask).where(GuardTask.kind == "announcement")
        )
        assert task.due_at.isoformat() == "2026-09-08T01:00:00"
    assert (await api.delete(root + "/contents/restriction/2")).status_code == 422


async def test_content_name_rejects_path_separator(api, guard_group):
    root = f"/api/groups/{guard_group}/guard"
    response = await api.put(
        root + "/contents",
        json={"kind": "reply", "name": "path/segment", "text": "hello"},
    )
    assert response.status_code == 422
    assert await store.record(guard_group, "reply", "path/segment") is None


async def test_deleting_announcement_cancels_only_its_pending_tasks(api, guard_group):
    roots = [
        f"/api/groups/{guard_group}/guard",
        f"/api/groups/{guard_group + 1}/guard",
    ]
    payload = {
        "kind": "announcement",
        "name": "future",
        "text": "hello",
        "due_at": "2099-09-08T09:00:00+08:00",
    }
    for root in roots:
        assert (await api.put(root + "/contents", json=payload)).status_code == 200

    response = await api.delete(roots[0] + "/contents/announcement/future")
    assert response.status_code == 200 and response.json() == {"removed": True}
    async with engine.new_session() as session:
        tasks = (
            await session.scalars(
                select(GuardTask).where(GuardTask.kind == "announcement")
            )
        ).all()
    assert {task.group_id: task.state for task in tasks} == {
        guard_group: "cancelled",
        guard_group + 1: "pending",
    }


async def test_model_secret_omit_preserves_and_empty_clears_without_echo(api):
    initial = {
        "base_url": "https://model.example/v1",
        "text_model": "test",
        "api_key": "test-secret-value",
    }
    assert (await api.put("/api/guard-ai", json=initial)).json()["has_api_key"]
    for extra in ({}, {"api_key": None}):
        response = await api.put(
            "/api/guard-ai", json={"text_model": "updated"} | extra
        )
        assert response.status_code == 200
        assert response.json()["has_api_key"]
        assert "test-secret-value" not in response.text
        assert (await store.ai_config()).api_key == "test-secret-value"
    response = await api.put("/api/guard-ai", json={"api_key": ""})
    assert not response.json()["has_api_key"]
    assert not (await store.ai_config()).api_key
    assert "api_key" not in (await api.get("/api/guard-ai")).json()


async def test_webhook_secret_required_and_valid_request_dispatched(api, monkeypatch):
    import main

    receiver = AsyncMock()
    monkeypatch.setattr(
        main, "config", SimpleNamespace(telegram_webhook_secret="webhook-test-secret")
    )
    monkeypatch.setattr(main.tg_bot, "put_update", receiver)
    for headers in ({}, {"X-Telegram-Bot-Api-Secret-Token": "wrong"}):
        assert (
            await api.post("/tapi/", json={"update_id": 12}, headers=headers)
        ).status_code == 403
    receiver.assert_not_awaited()
    response = await api.post(
        "/tapi/",
        json={"update_id": 12},
        headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-test-secret"},
    )
    assert response.status_code == 200 and response.json() == {"ok": True}
    receiver.assert_awaited_once()
    assert await receiver.call_args.args[0].json() == {"update_id": 12}
