"""System tests for the illustration preview / import / proxy APIs."""

import time

from models.illustrations import build_illust_from_api_dict


def _api_dict() -> dict:
    return {
        "id": "200",
        "title": "System Test Illust",
        "user": {"id": "456", "name": "Tester"},
        "page_count": 1,
        "sanity_level": 4,
        "x_restrict": 0,
        "tags": [{"name": "tag1"}],
        "caption": "caption",
        "illust_ai_type": 0,
        "image_urls": {"square_medium": "https://i.pximg.net/c/250x250/img-master/200_s.jpg"},
        "meta_single_page": {"original_image_url": "https://i.pximg.net/img-original/200_p0.jpg"},
    }


def test_preview_requires_pixiv_enabled(client, pixiv_disabled):
    response = client.post("/api/illustrations/preview", json={"pixiv_id": 200})
    assert response.status_code == 400


def test_preview_returns_metadata(client, pixiv_enabled, monkeypatch):
    async def fake_get_raw(pixiv_id: int) -> dict:
        return {"illust": _api_dict()}

    monkeypatch.setattr("services.pixiv.get_raw", fake_get_raw)
    response = client.post("/api/illustrations/preview", json={"pixiv_id": 200})
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "200"
    assert data["title"] == "System Test Illust"
    assert data["author_name"] == "Tester"
    assert data["page_count"] == 1
    assert data["preview_urls"] == ["https://i.pximg.net/c/250x250/img-master/200_s.jpg"]
    assert data["exists"] is False


def test_preview_pixiv_failure_returns_502(client, pixiv_enabled, monkeypatch):
    async def fake_get_raw(pixiv_id: int) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr("services.pixiv.get_raw", fake_get_raw)
    response = client.post("/api/illustrations/preview", json={"pixiv_id": 999})
    assert response.status_code == 502


def test_import_creates_task_and_finishes(client, pixiv_enabled, monkeypatch):
    async def fake_import(pixiv_id, *, bot=None, telegram_chat_ids=None, cleanup_messages=True, on_page_done=None):
        if on_page_done is not None:
            await on_page_done(1)
        saved = build_illust_from_api_dict(_api_dict())
        saved.file_urls = ["https://storage/200_p0.jpg"]
        from services.illustration_importer import IllustrationImportResult, ImportedPage

        return IllustrationImportResult(
            illustration=saved,
            created=True,
            telegram_cache_enabled=True,
            pages=[ImportedPage(index=0, storage_url="https://storage/200_p0.jpg", compressed_file_id=None, original_file_id=None)],
        )

    monkeypatch.setattr(
        "services.illustration_import_runner.import_illustration", fake_import
    )

    response = client.post(
        "/api/illustrations/import",
        json={"pixiv_id": 200, "title": "Edited Title"},
    )
    assert response.status_code == 200
    task = response.json()
    assert task["pixiv_id"] == "200"
    assert task["status"] in {"pending", "running"}

    # 轮询直到后台任务完成
    task_id = task["id"]
    for _ in range(50):
        time.sleep(0.2)
        detail = client.get(f"/api/illustrations/tasks/{task_id}").json()
        if detail["status"] in {"success", "failed"}:
            break
    assert detail["status"] == "success", detail
    assert detail["result"]["title"] == "Edited Title"
    assert detail["result"]["pages"][0]["storage_url"] == "https://storage/200_p0.jpg"


def test_import_requires_pixiv_enabled(client, pixiv_disabled):
    response = client.post("/api/illustrations/import", json={"pixiv_id": 200})
    assert response.status_code == 400


def test_manual_import_accepts_optional_metadata(client, monkeypatch):
    from models import Illustration
    from services.manual_illustration_importer import ManualImportResult

    captured = {}

    async def fake_manual(data, **kwargs):
        captured.update(kwargs)
        captured["data"] = data
        illustration = Illustration(id="manual_123", title=kwargs["title"])
        return ManualImportResult(illustration, "manual/manual_123/image.png")

    monkeypatch.setattr("routers.illustrations.import_manual_illustration", fake_manual)
    response = client.post(
        "/api/illustrations/manual",
        files={"image": ("image.png", b"png-data", "image/png")},
        data={"title": "手动图片", "is_ai": "true", "is_r18": "true"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "manual_123"
    assert captured["title"] == "手动图片"
    assert captured["author_name"] is None
    assert captured["is_ai"] is True
    assert captured["is_r18"] is True
    assert captured["data"] == b"png-data"


def test_manual_import_maps_mocked_validation_error(client, monkeypatch):
    """模拟导入服务拒绝文件，验证 HTTP 层不会把用户错误变成 500。"""

    async def reject_manual(*args, **kwargs):
        raise ValueError("仅支持 JPG、PNG、GIF 和 WebP 图片")

    monkeypatch.setattr("routers.illustrations.import_manual_illustration", reject_manual)
    response = client.post(
        "/api/illustrations/manual",
        files={"image": ("image.svg", b"<svg/>", "image/svg+xml")},
        data={"title": "不支持的图片"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "仅支持 JPG、PNG、GIF 和 WebP 图片"}


def test_manual_import_bounds_upload_read(client, monkeypatch):
    """Only read enough upload bytes for the importer to detect an oversize file."""

    monkeypatch.setattr("routers.illustrations.MAX_IMAGE_BYTES", 8)

    async def reject_oversize(data, **kwargs):
        assert data == b"x" * 9
        raise ValueError("图片不能超过 20 MB")

    monkeypatch.setattr(
        "routers.illustrations.import_manual_illustration", reject_oversize
    )
    response = client.post(
        "/api/illustrations/manual",
        files={"image": ("image.png", b"x" * 100, "image/png")},
        data={"title": "过大的图片"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "图片不能超过 20 MB"}


def test_task_list_and_missing_task(client, pixiv_enabled, monkeypatch):
    async def fake_import(pixiv_id, *, bot=None, telegram_chat_ids=None, cleanup_messages=True, on_page_done=None):
        if on_page_done is not None:
            await on_page_done(1)
        saved = build_illust_from_api_dict(_api_dict())
        from services.illustration_importer import IllustrationImportResult, ImportedPage

        return IllustrationImportResult(
            illustration=saved,
            created=True,
            telegram_cache_enabled=True,
            pages=[ImportedPage(index=0, storage_url="https://storage/x", compressed_file_id=None, original_file_id=None)],
        )

    monkeypatch.setattr(
        "services.illustration_import_runner.import_illustration", fake_import
    )
    client.post("/api/illustrations/import", json={"pixiv_id": 200})
    for _ in range(50):
        time.sleep(0.2)
        if client.get("/api/illustrations/tasks").json()["total"] >= 1:
            break

    data = client.get("/api/illustrations/tasks").json()
    assert data["total"] >= 1

    assert client.get("/api/illustrations/tasks/99999").status_code == 404


def test_proxy_rejects_non_pixiv_domain(client):
    response = client.get("/api/illustrations/image", params={"url": "https://evil.com/x.jpg"})
    assert response.status_code == 400


def test_proxy_rejects_untrusted_url_components(client):
    urls = [
        "http://i.pximg.net/x.jpg",
        "https://user@i.pximg.net/x.jpg",
        "https://i.pximg.net:443/x.jpg",
        "https://i.pximg.net:invalid/x.jpg",
        "https://i.pximg.net//evil.example/x.jpg",
    ]

    for url in urls:
        response = client.get("/api/illustrations/image", params={"url": url})
        assert response.status_code == 400, url


def test_proxy_returns_image(client, monkeypatch):
    fetched_urls = []

    async def fake_fetch(url: str) -> bytes:
        fetched_urls.append(url)
        return b"\xff\xd8fakejpeg"

    monkeypatch.setattr("routers.illustrations._fetch_pixiv_bytes", fake_fetch)
    response = client.get(
        "/api/illustrations/image",
        params={
            "url": "https://i.pximg.net/img-master/200_p0_master1200.jpg?token=test#ignored"
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8fakejpeg"
    assert fetched_urls == ["/img-master/200_p0_master1200.jpg?token=test"]
