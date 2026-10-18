"""Service regressions: finite retries, cache refresh, SDK threading and policies."""

import asyncio
import importlib
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import aiorwlock
import pytest


@pytest.fixture(autouse=True)
def isolated_file_locks(monkeypatch):
    from services.file_service import file_lock

    monkeypatch.setattr(file_lock, "file_locks", {})
    monkeypatch.setattr(file_lock, "dict_lock", aiorwlock.RWLock())


@pytest.mark.parametrize("status", [204, 206, 304])
async def test_download_unexpected_status_has_bounded_retries(tmp_path, monkeypatch, status):
    module = importlib.import_module("services.file_service.download_file")
    monkeypatch.setattr(module, "file_path", str(tmp_path))
    response = MagicMock(status=status)
    response.raise_for_status.return_value = None
    response.__aenter__.return_value = response
    session = MagicMock()
    session.get.return_value = response
    session.__aenter__.return_value = session
    sessions = MagicMock(return_value=session)
    monkeypatch.setattr(module.aiohttp, "ClientSession", sessions)
    with pytest.raises(aiohttp.ClientError, match="Unexpected download status"):
        await asyncio.wait_for(module.download_file("image.jpg", "https://example/image"), timeout=2)
    assert sessions.call_count == 5
    assert not list(tmp_path.iterdir())
    # Failure must release the per-file lock and permit another attempt.
    response.status = 200
    response.content.read = AsyncMock(return_value=b"image")
    await asyncio.wait_for(module.download_file("image.jpg", "https://example/image"), timeout=2)
    assert (tmp_path / "image.jpg").read_bytes() == b"image"


async def test_failed_download_refresh_preserves_old_cache(tmp_path, monkeypatch):
    module = importlib.import_module("services.file_service.download_file")
    monkeypatch.setattr(module, "file_path", str(tmp_path))
    path = tmp_path / "image.jpg"
    path.write_bytes(b"old")
    response = MagicMock(status=204)
    response.__aenter__.return_value = response
    session = MagicMock()
    session.get.return_value = response
    session.__aenter__.return_value = session
    monkeypatch.setattr(module.aiohttp, "ClientSession", MagicMock(return_value=session))
    with pytest.raises(aiohttp.ClientError):
        await module.download_file("image.jpg", "https://example/image", replace=True)
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


async def test_file_cache_refresh_is_explicit_and_atomic(tmp_path, monkeypatch):
    module = importlib.import_module("services.file_service.get_file")
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(module, "CACHE_ROOT", cache)
    monkeypatch.setattr(module, "_LOCAL_STORAGE_ROOT", tmp_path)
    source = tmp_path / "source.jpg"
    source.write_bytes(b"first")
    assert await module.get_file("image.jpg", source.name) == b"first"
    source.write_bytes(b"second")
    assert await module.get_file("image.jpg", source.name) == b"first"
    assert await module.get_file("image.jpg", source.name, refresh=True) == b"second"
    source.unlink()
    with pytest.raises(FileNotFoundError):
        await module.get_file("image.jpg", source.name, refresh=True)
    assert await module.get_file("image.jpg") == b"second"


@pytest.mark.parametrize("chat_ids", [None, [123]])
async def test_import_without_bot_preserves_telegram_cache_and_refreshes_bytes(monkeypatch, chat_ids):
    from services import illustration_importer as module
    from services.image_service.get_image import resource_for_illustration

    existing = SimpleNamespace(compressed_file_ids=["photo"], original_file_ids=["document"])
    illust = SimpleNamespace(
        id="123", page_count=1, origin_urls=["https://origin/image.jpg"], file_ext=[".jpg"],
        file_urls=[None], compressed_file_ids=[None], original_file_ids=[None],
    )
    monkeypatch.setattr(module.pixiv, "enabled", True)
    monkeypatch.setattr(module.pixiv, "get_illust_info_by_pixiv_id", AsyncMock(return_value=illust))
    monkeypatch.setattr(module.illust_registry, "get_illust_info", AsyncMock(return_value=existing))
    monkeypatch.setattr(module.illust_registry, "save_illustration", AsyncMock(side_effect=lambda value: value))
    monkeypatch.setattr(module.config_registry, "get_config", AsyncMock(return_value=True))
    storage = SimpleNamespace(join_path=lambda *args: "/".join(args), upload=AsyncMock(return_value="https://storage/image.jpg"))
    monkeypatch.setattr(module, "use_storage", AsyncMock(return_value=storage))
    fetch = AsyncMock(return_value=b"new")
    monkeypatch.setattr(module, "get_file", fetch)
    result = await module.import_illustration(123, bot=None, telegram_chat_ids=chat_ids)
    assert result.illustration.compressed_file_ids == ["photo"]
    assert result.illustration.original_file_ids == ["document"]
    fetch.assert_awaited_once_with(filename="123_00.jpg", url="https://origin/image.jpg", refresh=True)
    assert resource_for_illustration(illust, 0).filename == "123_00.jpg"


async def test_backblaze_network_calls_run_outside_event_loop(monkeypatch):
    module = importlib.import_module("services.storage_service.backblaze")
    from services.storage_service.backblaze import BackBlaze

    storage = BackBlaze()
    loop_thread = threading.get_ident()
    calls = []

    def off_thread(result):
        def call(*args, **kwargs):
            calls.append(threading.get_ident())
            assert threading.get_ident() != loop_thread
            return result
        return call

    bucket = SimpleNamespace(upload_bytes=off_thread(object()))
    storage.b2_api = SimpleNamespace(authorize_account=off_thread(None), get_bucket_by_name=off_thread(bucket))
    monkeypatch.setattr(
        module.config_registry, "get_backblaze_config",
        AsyncMock(return_value=SimpleNamespace(app_id="id", app_key="key", bucket_name="bucket", base_path="", base_url="https://cdn")),
    )
    assert await storage.upload(b"data", "image.jpg") == "https://cdn/image.jpg"
    assert len(calls) == 3


@pytest.mark.parametrize("global_allowed, local_allowed", [(False, True), (True, False), (True, True)])
async def test_random_images_obey_global_and_local_r18g_flags(global_allowed, local_allowed):
    from models import Illustration
    from registries import config_registry, engine, illust_registry

    async with engine.new_session() as session:
        session.add(Illustration(id="1", title="test", author_id="2", author_name="artist", page_count=1, sanity_level=3, r18g=True, x_restrict=0, tags=[], is_ai=False))
        await session.commit()
    await config_registry.update_config("allow_r18g", global_allowed)
    result = await illust_registry.random_illust(r18g=local_allowed)
    assert (result is not None) is (global_allowed and local_allowed)


@pytest.mark.parametrize("global_allowed, local_allowed", [(False, True), (True, False), (True, True)])
async def test_fixed_push_rechecks_global_r18g_flag(global_allowed, local_allowed):
    from models import Group, Illustration
    from registries import config_registry, engine
    from services.image_push import _image_policy_reason

    async with engine.new_session() as session:
        session.add(Group(id=1, allow_r18g=local_allowed))
        await session.commit()
    await config_registry.update_config("allow_r18g", global_allowed)
    reason = await _image_policy_reason(1, Illustration(sanity_level=3, r18g=True))
    assert (reason is None) is (global_allowed and local_allowed)


async def test_http_cache_refresh_forwards_replace(tmp_path, monkeypatch):
    module = importlib.import_module("services.file_service.get_file")
    monkeypatch.setattr(module, "CACHE_ROOT", tmp_path)
    cached = tmp_path / "image.jpg"
    cached.write_bytes(b"old")

    async def download(filename, url, *, replace):
        assert replace is True
        cached.write_bytes(b"new")

    downloader = AsyncMock(side_effect=download)
    monkeypatch.setattr(module, "download_file", downloader)
    assert await module.get_file("image.jpg", "https://example/image", refresh=True) == b"new"
    downloader.assert_awaited_once()


async def test_download_timeouts_stop_after_five_attempts(tmp_path, monkeypatch):
    module = importlib.import_module("services.file_service.download_file")
    monkeypatch.setattr(module, "file_path", str(tmp_path))
    sessions = MagicMock(side_effect=TimeoutError)
    monkeypatch.setattr(module.aiohttp, "ClientSession", sessions)
    with pytest.raises(TimeoutError):
        await module.download_file("image.jpg", "https://example/image")
    assert sessions.call_count == 5
    assert not list(tmp_path.iterdir())
