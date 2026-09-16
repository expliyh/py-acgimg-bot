"""API and storage safety coverage for the illustration gallery."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import select

from models import Illustration, IllustrationImportTask
from registries import engine


@pytest.fixture
async def api():
    import main

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        yield client


async def _seed(*rows: Illustration) -> None:
    async with engine.new_session() as session:
        session.add_all(list(rows))
        await session.commit()


def _illust(
    ident: str,
    *,
    source_type: str = "pixiv",
    pages: int = 1,
    file_urls: list[str | None] | None = None,
    title: str | None = None,
    tags: list[str] | None = None,
    sanity: int = 5,
    r18g: bool = False,
    x_restrict: int = 0,
    is_ai: bool = False,
) -> Illustration:
    return Illustration(
        id=ident,
        title=title or f"Title {ident}",
        author_id="author-1",
        author_name="Artist",
        page_count=pages,
        sanity_level=sanity,
        r18g=r18g,
        x_restrict=x_restrict,
        tags=tags or [],
        caption=f"caption {ident}",
        is_ai=is_ai,
        file_urls=file_urls or [None] * pages,
        compressed_file_ids=["old-compressed"] * pages,
        original_file_ids=["old-original"] * pages,
        origin_urls=[f"https://i.pximg.net/{ident}/{index}.jpg" for index in range(pages)],
        file_ext=[".jpg"] * pages,
        source_type=source_type,
        source_url="https://source.example/item",
        author_url="https://source.example/artist",
    )


async def _get(ident: str) -> Illustration | None:
    async with engine.new_session() as session:
        return await session.get(Illustration, ident)


async def test_list_search_filters_sort_and_detail(api):
    await _seed(
        _illust("300", title="Blue sky", tags=["sky", "blue"], sanity=2),
        _illust("200", source_type="manual", title="Manual flower", tags=["flower"], is_ai=True),
        _illust("100", title="Red sky", tags=["red"], r18g=True, x_restrict=2),
    )

    response = await api.get("/api/illustrations", params={"page_size": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [item["id"] for item in data["items"]] == ["300", "200"]
    assert data["page_size"] == 2 and data["pages"] == 2
    assert data["items"][0]["thumbnail_url"] is None

    response = await api.get("/api/illustrations", params={"q": "flower", "source_type": "manual"})
    assert [item["id"] for item in response.json()["items"]] == ["200"]
    response = await api.get("/api/illustrations", params={"q": "author-1"})
    assert {item["id"] for item in response.json()["items"]} == {"100", "200", "300"}
    response = await api.get("/api/illustrations", params={"r18g": "true", "x_restrict": 2})
    assert [item["id"] for item in response.json()["items"]] == ["100"]
    response = await api.get("/api/illustrations", params={"sort_by": "not-a-column"})
    assert response.status_code == 422

    response = await api.get("/api/illustrations/100")
    assert response.status_code == 200
    detail = response.json()
    assert detail["pages"] == [{
        "index": 0,
        "media_url": "/api/illustrations/100/pages/0/media",
        "has_storage_url": False,
    }]
    assert "origin_urls" not in detail


async def test_local_media_endpoint_rejects_missing_and_path_traversal(api, tmp_path, monkeypatch):
    root = tmp_path / "storage"
    root.mkdir()
    image = root / "pixiv" / "400" / "0.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"jpeg-data")

    async def local_config():
        from registries.config_registry import LocalStorageConfig

        return LocalStorageConfig(root_path=str(root), base_url=None)

    async def empty_backblaze():
        from registries.config_registry import BackBlazeConfig

        return BackBlazeConfig()

    async def empty_webdav():
        from registries.config_registry import WebDavConfig

        return WebDavConfig()

    monkeypatch.setattr("registries.config_registry.get_local_storage_config", local_config)
    monkeypatch.setattr("registries.config_registry.get_backblaze_config", empty_backblaze)
    monkeypatch.setattr("registries.config_registry.get_webdav_config", empty_webdav)
    await _seed(_illust("400", file_urls=["pixiv/400/0.jpg"]))

    response = await api.get("/api/illustrations/400/pages/0/media")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"jpeg-data"

    await _seed(_illust("402", file_urls=[str(image)]))
    response = await api.get("/api/illustrations/402/pages/0/media")
    assert response.status_code == 200
    assert response.content == b"jpeg-data"

    await _seed(_illust("401", file_urls=["../outside.jpg"]))
    response = await api.get("/api/illustrations/401/pages/0/media")
    assert response.status_code in {404, 502}

    response = await api.get("/api/illustrations/400/pages/2/media")
    assert response.status_code == 404


async def test_patch_and_bulk_update_preserve_independent_flags(api):
    await _seed(_illust("500", r18g=False, x_restrict=0), _illust("501", r18g=True, x_restrict=2))

    response = await api.patch(
        "/api/illustrations/500",
        json={"title": None, "tags": [], "r18g": True, "x_restrict": 0},
    )
    assert response.status_code == 200
    assert response.json()["title"] is None
    assert response.json()["r18g"] is True and response.json()["x_restrict"] == 0

    response = await api.patch("/api/illustrations/500", json={})
    assert response.status_code == 422
    response = await api.patch("/api/illustrations/500", json={"r18g": None})
    assert response.status_code == 422

    response = await api.post(
        "/api/illustrations/bulk/update",
        json={"ids": ["500", "501"], "patch": {"is_ai": True}},
    )
    assert response.status_code == 200
    assert response.json()["updated_ids"] == ["500", "501"]
    assert (await _get("501")).is_ai is True

    response = await api.post(
        "/api/illustrations/bulk/update",
        json={"ids": ["500", "does-not-exist"], "patch": {"title": "atomic"}},
    )
    assert response.status_code == 404
    assert (await _get("500")).title is None


async def test_delete_shared_files_and_active_task_conflict(api, monkeypatch):
    shared = "shared/600.jpg"
    unique = "unique/601.jpg"
    await _seed(_illust("600", file_urls=[shared]), _illust("601", file_urls=[shared, unique], pages=2))
    deleted: list[str] = []

    async def fake_delete(url: str):
        deleted.append(url)

    monkeypatch.setattr("services.illustration_gallery.delete_media_url", fake_delete)
    response = await api.post("/api/illustrations/bulk/delete", json={"ids": ["600", "601"]})
    assert response.status_code == 200
    data = response.json()
    assert data["deleted_urls"] == 2
    assert data["shared_urls"] == 0
    assert sorted(deleted) == sorted([shared, unique])
    assert await _get("600") is None and await _get("601") is None

    await _seed(_illust("602", file_urls=["busy.jpg"]))
    async with engine.new_session() as session:
        session.add(IllustrationImportTask(pixiv_id="602", status="running"))
        await session.commit()
    response = await api.delete("/api/illustrations/602")
    assert response.status_code == 409
    assert await _get("602") is not None


async def test_delete_reports_cleanup_failure_after_commit(api, monkeypatch):
    await _seed(_illust("603", file_urls=["broken/603.jpg"]))

    async def failing_delete(url: str):
        raise ValueError("provider rejected delete")

    monkeypatch.setattr("services.illustration_gallery.delete_media_url", failing_delete)
    response = await api.delete("/api/illustrations/603")
    assert response.status_code == 200
    data = response.json()
    assert data["removed_ids"] == ["603"]
    assert data["deleted_urls"] == 0
    assert data["cleanup_failures"][0]["page"] == 0
    assert await _get("603") is None


async def test_bulk_refresh_rejects_mixed_selection_before_creating_tasks(api, pixiv_enabled):
    await _seed(_illust("700"), _illust("manual_700", source_type="manual"))
    response = await api.post(
        "/api/illustrations/bulk/refresh",
        json={"ids": ["700", "manual_700"]},
    )
    assert response.status_code == 422
    async with engine.new_session() as session:
        assert (await session.scalars(select(IllustrationImportTask))).all() == []


async def test_refresh_is_serial_and_preserves_local_metadata(api, pixiv_enabled, monkeypatch):
    await _seed(
        _illust(
            "800",
            file_urls=["old/800-0.jpg", "old/800-1.jpg"],
            pages=2,
            title="  Local title  ",
            tags=["local"],
        ),
        _illust(
            "801",
            file_urls=["old/801-0.jpg"],
            pages=1,
            title="Second title",
        ),
    )
    calls: list[int] = []
    deleted: list[str] = []

    async def fake_delete(url: str):
        deleted.append(url)

    async def fake_import(pixiv_id: int, *, bot=None, telegram_chat_ids=None, cleanup_messages=True, on_page_done=None):
        calls.append(pixiv_id)
        if on_page_done:
            await on_page_done(1)
        from services.illustration_importer import IllustrationImportResult, ImportedPage

        current_pages = 1 if pixiv_id == 800 else 1
        fresh = _illust(
            str(pixiv_id),
            pages=current_pages,
            file_urls=[f"new/{pixiv_id}-0.jpg"],
            title="Pixiv title",
            tags=["pixiv"],
        )
        fresh.author_name = "Pixiv author"
        fresh.source_url = None
        fresh.author_url = None
        return IllustrationImportResult(
            illustration=fresh,
            created=False,
            telegram_cache_enabled=False,
            pages=[ImportedPage(0, fresh.file_urls[0], None, None)],
        )

    monkeypatch.setattr("services.illustration_import_runner.import_illustration", fake_import)
    monkeypatch.setattr("services.illustration_import_runner.delete_media_url", fake_delete)

    response = await api.post("/api/illustrations/bulk/refresh", json={"ids": ["800", "801"]})
    assert response.status_code == 200
    task_ids = [task["id"] for task in response.json()["tasks"]]
    assert len(task_ids) == 2

    for _ in range(100):
        await asyncio.sleep(0.01)
        states = [(await api.get(f"/api/illustrations/tasks/{task_id}")).json()["status"] for task_id in task_ids]
        if all(state in {"success", "failed"} for state in states):
            break
    assert states == ["success", "success"]
    assert calls == [800, 801]

    refreshed = await _get("800")
    assert refreshed.title == "  Local title  "
    assert refreshed.tags == ["local"]
    assert refreshed.author_name == "Artist"
    assert refreshed.source_url == "https://source.example/item"
    assert refreshed.page_count == 1
    assert refreshed.compressed_file_ids == [None]
    assert refreshed.original_file_ids == [None]
    assert set(deleted) == {"old/800-0.jpg", "old/800-1.jpg", "old/801-0.jpg"}


async def test_refresh_failure_keeps_previous_record(api, pixiv_enabled, monkeypatch):
    await _seed(_illust("810", title="Keep me", file_urls=["old/810.jpg"]))

    async def failing_import(*args, **kwargs):
        raise RuntimeError("Pixiv unavailable")

    monkeypatch.setattr("services.illustration_import_runner.import_illustration", failing_import)
    response = await api.post("/api/illustrations/810/refresh")
    assert response.status_code == 200
    task_id = response.json()["id"]
    for _ in range(100):
        await asyncio.sleep(0.01)
        task = (await api.get(f"/api/illustrations/tasks/{task_id}")).json()
        if task["status"] in {"success", "failed"}:
            break
    assert task["status"] == "failed"
    previous = await _get("810")
    assert previous.title == "Keep me"
    assert previous.file_urls == ["old/810.jpg"]
