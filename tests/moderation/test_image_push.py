"""Image push validation, queueing and per-group delivery semantics."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from models import Group, GuardTask, Illustration, ImagePushDelivery
from registries import engine, illust_registry
from services import image_push


@pytest.fixture
async def push_api(guard_group, guard_bot, monkeypatch):
    import main
    from bot import tg_bot

    monkeypatch.setattr(tg_bot, "tg_bot", guard_bot)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        yield client


def test_pid_spec_supports_optional_page():
    assert image_push.parse_pid_spec("12345") == (12345, None)
    assert image_push.parse_pid_spec("12345:2") == (12345, 2)
    with pytest.raises(ValueError):
        image_push.parse_pid_spec("12345:0")


async def _add_illustration(pid: str = "12345", pages: int = 2):
    illust = Illustration(
        id=pid,
        title="Push test",
        author_id="9",
        author_name="Tester",
        page_count=pages,
        sanity_level=4,
        r18g=False,
        x_restrict=0,
        tags=[],
        caption=None,
        is_ai=False,
        file_urls=[f"https://storage/{pid}-{i}.jpg" for i in range(pages)],
        compressed_file_ids=[None] * pages,
        original_file_ids=[None] * pages,
        origin_urls=[f"https://cdn/{pid}-{i}.jpg" for i in range(pages)],
        file_ext=[".jpg"] * pages,
    )
    return await illust_registry.save_illustration(illust)


async def test_fixed_same_batch_uses_one_page_for_all_groups(
    guard_group, guard_bot, monkeypatch
):
    other_group = guard_group + 1
    async with engine.new_session() as session:
        session.add(Group(id=other_group))
        await session.commit()
    await _add_illustration()
    monkeypatch.setattr(image_push.random, "randrange", lambda count: 1)
    sender = AsyncMock(return_value=SimpleNamespace(message_id=88))
    monkeypatch.setattr(image_push, "send_illustration_photo", sender)

    batch = await image_push.create_batch(
        {
            "target_scope": "selected",
            "group_ids": [guard_group, other_group],
            "mode": "fixed_same",
            "pid": "12345",
        }
    )
    worker = image_push.ImagePushWorker(guard_bot)
    await worker.tick()

    async with engine.new_session() as session:
        rows = (
            await session.scalars(
                select(ImagePushDelivery).where(ImagePushDelivery.batch_id == batch.id)
            )
        ).all()
    assert {row.state for row in rows} == {"success"}
    assert {row.page for row in rows} == {1}
    assert sender.await_count == 2


async def test_missing_pid_is_imported_once(monkeypatch):
    imported = await _add_illustration("54321", pages=1)
    # Hide the existing record for the first lookup, then return it after the
    # importer has persisted it. This models the missing-PID path without a
    # Pixiv network call.
    calls = 0

    async def fake_lookup(pid):
        nonlocal calls
        calls += 1
        return None if calls == 1 else imported

    imported_result = SimpleNamespace(illustration=imported)
    importer = AsyncMock(return_value=imported_result)
    monkeypatch.setattr(image_push.illust_registry, "get_illust_info", fake_lookup)
    monkeypatch.setattr(image_push.pixiv, "enabled", True)
    monkeypatch.setattr(image_push, "import_illustration", importer)
    locks = {}

    assert await image_push._ensure_illustration(54321, locks) is imported
    assert await image_push._ensure_illustration(54321, locks) is imported
    importer.assert_awaited_once()


async def test_api_creates_plan_and_manual_batch(push_api, guard_group):
    root = "/api/image-push"
    payload = {
        "name": "morning push",
        "target_scope": "selected",
        "group_ids": [guard_group],
        "mode": "fixed_same",
        "pid": "12345:2",
        "repeat": "daily",
        "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "timezone": "Asia/Shanghai",
    }
    response = await push_api.post(root + "/plans", json=payload)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["mode"] == "fixed_same"
    assert plan["pid"] == "12345:2"

    manual = await push_api.post(
        root + "/manual",
        json={
            "target_scope": "selected",
            "group_ids": [guard_group],
            "mode": "random_different",
        },
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["trigger"] == "manual"
