"""Service units that stay on sqlite or fakes instead of Telegram, Pixiv, or WebDAV."""

from __future__ import annotations

import asyncio
import io
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image
from telegram import Chat

from defines import GroupStatus, MessageType, UserStatus
from models import Group, User
from registries.config_registry import (
    BackBlazeConfig,
    LocalStorageConfig,
    Token,
    WebDavConfig,
)
from tests.unit.telegram_fakes import Bag, make_context, make_message, make_update, make_user


class _Response:
    def __init__(self, status=200, body=b"\x89PNG", headers=None, text="err"):
        self.status = status
        self.headers = headers or {"Content-Type": "image/png"}
        self._body = body
        self._text = text
        self.content = SimpleNamespace(read=AsyncMock(return_value=body))

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url):
        self.calls.append((method, url))
        return self.responses.pop(0)

    def request(self, method, url):
        return self._next(method, url)

    def put(self, url, data=None):
        return self._next("PUT", url)

    def get(self, url, allow_redirects=True):
        return self._next("GET", url)

    def delete(self, url, allow_redirects=True):
        return self._next("DELETE", url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def test_media_path_helpers(tmp_path):
    from services import illustration_media as media

    assert media._media_type("https://cdn.example/a.png") == "image/png"
    assert media._media_type("https://cdn.example/a.txt") == "application/octet-stream"
    assert media._base_matches("https://cdn.example/a", None) is False
    assert media._base_matches("http://user:pw@cdn.example/a", "http://cdn.example") is False
    assert media._base_matches("ftp://cdn.example/a", "http://cdn.example") is False
    assert media._base_matches("https://other.example/a", "https://cdn.example") is False
    assert media._base_matches("https://cdn.example:8443/a", "https://cdn.example/files") is False
    assert media._base_matches("https://cdn.example/files/a.png", "https://cdn.example/files") is True
    assert media._base_matches("https://CDN.example/files", "https://cdn.example/files") is True
    assert media._default_port("https") == 443
    assert media._default_port("ws") is None
    with pytest.raises(media.MediaAccessError):
        media._safe_relative_name("")
    with pytest.raises(media.MediaAccessError):
        media._safe_relative_name("a/%2e%2e/b")
    with pytest.raises(media.MediaAccessError):
        media._safe_relative_name("bad\x00name")
    assert media._safe_relative_name("folder/a%20b.png") == "folder/a b.png"
    root = media._local_root(str(tmp_path))
    nested = tmp_path / "folder"
    nested.mkdir()
    assert media._safe_local_path(root, "folder").is_relative_to(root)
    with pytest.raises(media.MediaAccessError):
        media._safe_local_path(root, "../outside")
    inside = tmp_path / "pic.png"
    inside.write_bytes(b"x")
    assert media._absolute_local_relative(root, str(inside)).endswith("pic.png")
    with pytest.raises(media.MediaAccessError):
        media._absolute_local_relative(root, "/tmp")
    config = LocalStorageConfig(root_path=str(tmp_path), base_url="https://cdn.example/files")
    assert media._local_relative_reference("folder/pic.png", config) == "folder/pic.png"
    assert media._local_relative_reference(f"file://{inside}", config).endswith("pic.png")
    with pytest.raises(media.MediaAccessError):
        media._local_relative_reference("https://evil.example/a.png", config)
    with pytest.raises(media.MediaAccessError):
        media._relative_url_path("https://cdn.example/files", "https://cdn.example/files")


async def test_media_read_and_delete(monkeypatch, tmp_path):
    from services import illustration_media as media

    local = LocalStorageConfig(root_path=str(tmp_path), base_url="https://cdn.example/files")
    blaze = BackBlazeConfig(base_url="https://b2.example/bucket")
    web = WebDavConfig(
        endpoint="https://dav.example/remote",
        username="user",
        password="secret",
        public_base_url="https://pub.example/files",
    )
    monkeypatch.setattr(media.config_registry, "get_local_storage_config", AsyncMock(return_value=local))
    monkeypatch.setattr(media.config_registry, "get_backblaze_config", AsyncMock(return_value=blaze))
    monkeypatch.setattr(media.config_registry, "get_webdav_config", AsyncMock(return_value=web))

    picture = tmp_path / "art.png"
    picture.write_bytes(b"png-bytes")
    content = await media.read_media_url("art.png")
    assert content.data == b"png-bytes"
    await media.delete_media_url("art.png")
    assert not picture.exists()
    await media.delete_media_url("missing.png")

    huge = tmp_path / "huge.png"
    huge.write_bytes(b"x" * (media.MAX_MEDIA_BYTES + 1))
    with pytest.raises(media.MediaAccessError):
        await media.read_media_url("huge.png")
    with pytest.raises(FileNotFoundError):
        await media.read_media_url("   ")
    with pytest.raises(media.MediaAccessError):
        await media.read_media_url("https://evil.example/a.png")

    ok = _Response()
    monkeypatch.setattr(media.aiohttp, "ClientSession", lambda *args, **kwargs: _Session([ok]))
    loaded = await media.read_media_url("https://b2.example/bucket/art.png")
    assert loaded.media_type == "image/png"

    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(status=404)]),
    )
    with pytest.raises(FileNotFoundError):
        await media._read_http("https://b2.example/bucket/missing.png")
    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(status=500)]),
    )
    with pytest.raises(media.MediaAccessError):
        await media._read_http("https://b2.example/bucket/missing.png")
    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(headers={"Content-Length": "nope"})]),
    )
    with pytest.raises(media.MediaAccessError):
        await media._read_http("https://b2.example/bucket/a.png")
    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(headers={"Content-Length": str(media.MAX_MEDIA_BYTES + 5)})]),
    )
    with pytest.raises(media.MediaAccessError):
        await media._read_http("https://b2.example/bucket/a.png")
    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(body=b"x" * (media.MAX_MEDIA_BYTES + 1))]),
    )
    with pytest.raises(media.MediaAccessError):
        await media._read_http("https://b2.example/bucket/a.png")
    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(headers={"Content-Type": "text/html"})]),
    )
    with pytest.raises(media.MediaAccessError):
        await media._read_http("https://b2.example/bucket/a.png")
    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(headers={"Content-Type": "application/octet-stream"})]),
    )
    octet = await media._read_http("https://b2.example/bucket/a.png")
    assert octet.media_type == "image/png"

    class BrokenSession(_Session):
        async def __aenter__(self):
            raise media.aiohttp.ClientError("down")

    monkeypatch.setattr(media.aiohttp, "ClientSession", lambda *args, **kwargs: BrokenSession([]))
    with pytest.raises(media.MediaAccessError):
        await media._read_http("https://b2.example/bucket/a.png")

    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(status=204)]),
    )
    await media.delete_media_url("https://pub.example/files/art.png")
    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(status=404)]),
    )
    await media.delete_media_url("https://dav.example/remote/art.png")
    monkeypatch.setattr(
        media.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: _Session([_Response(status=500)]),
    )
    with pytest.raises(media.MediaAccessError):
        await media.delete_media_url("https://dav.example/remote/art.png")
    await media.delete_media_url("")

    monkeypatch.setattr(media.config_registry, "get_local_storage_config", AsyncMock(side_effect=RuntimeError("cfg")))
    with pytest.raises(media.MediaAccessError):
        await media._resolve_provider("art.png")
    monkeypatch.setattr(media.config_registry, "get_local_storage_config", AsyncMock(return_value=local))
    monkeypatch.setattr(media.config_registry, "get_backblaze_config", AsyncMock(side_effect=RuntimeError("cfg")))
    with pytest.raises(media.MediaAccessError):
        await media._resolve_provider("https://pub.example/files/a.png")

    bucket = Mock()
    version = Mock()
    bucket.list_file_versions.return_value = [version]
    monkeypatch.setattr(media.backblaze, "ensure_ready", AsyncMock())
    monkeypatch.setattr(media.backblaze, "bucket", bucket)
    monkeypatch.setattr(media.config_registry, "get_backblaze_config", AsyncMock(return_value=blaze))
    await media.delete_media_url("https://b2.example/bucket/art.png")
    version.delete.assert_called()
    monkeypatch.setattr(media.backblaze, "bucket", None)
    with pytest.raises(media.MediaAccessError):
        await media.delete_media_url("https://b2.example/bucket/art.png")
    monkeypatch.setattr(media.backblaze, "bucket", bucket)
    bucket.list_file_versions.side_effect = RuntimeError("sdk")
    with pytest.raises(media.MediaAccessError):
        await media.delete_media_url("https://b2.example/bucket/art.png")
    bucket.list_file_versions.side_effect = FileNotFoundError("gone")
    await media.delete_media_url("https://b2.example/bucket/art.png")


async def test_webdav_upload(monkeypatch):
    from services.storage_service.webdav import WebDavStorage

    storage = WebDavStorage()
    monkeypatch.setattr(
        "services.storage_service.webdav.config_registry.get_webdav_config",
        AsyncMock(return_value=WebDavConfig(endpoint=None)),
    )
    with pytest.raises(RuntimeError):
        await storage.upload(b"a", "a.png", "nested/dir")

    storage = WebDavStorage()
    monkeypatch.setattr(
        "services.storage_service.webdav.config_registry.get_webdav_config",
        AsyncMock(
            return_value=WebDavConfig(
                endpoint="https://dav.example/remote",
                username="user",
                password="pw",
                base_path="base",
                public_base_url="https://pub.example/files/",
            )
        ),
    )
    session = _Session([_Response(status=201), _Response(status=405), _Response(status=204)])
    monkeypatch.setattr("services.storage_service.webdav.ClientSession", lambda *args, **kwargs: session)
    url = await storage.upload(b"data", "a.png", "nested")
    assert url.startswith("https://pub.example/files/")
    assert any(call[0] == "MKCOL" for call in session.calls)

    storage._configured = False
    bad = _Session([_Response(status=500, text="no")])
    monkeypatch.setattr("services.storage_service.webdav.ClientSession", lambda *args, **kwargs: bad)
    with pytest.raises(RuntimeError):
        await storage.upload(b"data", "a.png", "nested")

    storage._configured = False
    rejected = _Session([_Response(status=201), _Response(status=201), _Response(status=403, text="denied")])
    monkeypatch.setattr("services.storage_service.webdav.ClientSession", lambda *args, **kwargs: rejected)
    with pytest.raises(RuntimeError):
        await storage.upload(b"data", "a.png", "nested")

    anonymous = WebDavStorage()
    monkeypatch.setattr(
        "services.storage_service.webdav.config_registry.get_webdav_config",
        AsyncMock(return_value=WebDavConfig(endpoint="https://dav.example/remote", public_base_url=None)),
    )
    plain = _Session([_Response(status=201)])
    monkeypatch.setattr("services.storage_service.webdav.ClientSession", lambda *args, **kwargs: plain)
    uploaded = await anonymous.upload(b"data", "root.png")
    assert uploaded.startswith("https://dav.example/remote/")


def _message(**attrs):
    base = dict(
        message_id=1,
        text=None,
        caption=None,
        photo=None,
        video=None,
        animation=None,
        audio=None,
        voice=None,
        document=None,
        sticker=None,
        contact=None,
        location=None,
        venue=None,
        video_note=None,
        invoice=None,
        successful_payment=None,
        game=None,
        poll=None,
        dice=None,
        new_chat_members=None,
        left_chat_member=None,
        new_chat_title=None,
        new_chat_photo=None,
        delete_chat_photo=None,
        group_chat_created=None,
        supergroup_chat_created=None,
        channel_chat_created=None,
        migrate_to_chat_id=None,
        migrate_from_chat_id=None,
        pinned_message=None,
        connected_website=None,
        passport_data=None,
        proximity_alert_triggered=None,
        voice_chat_scheduled=None,
        voice_chat_started=None,
        voice_chat_ended=None,
        voice_chat_participants_invited=None,
        message_auto_delete_timer_changed=None,
        reply_markup=None,
        date=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    base.update(attrs)
    return Bag(**base)


async def test_message_logging_persists_group_and_private(monkeypatch):
    from services import message_logging as logging_service

    assert logging_service._preview_text("") is None
    assert logging_service._preview_text("x" * 200).endswith("...")
    assert logging_service._extract_user_display_name(None) is None
    assert logging_service._extract_user_display_name(make_user(full_name="", username="u")) == "u"
    assert logging_service._admin_list_changed(None, [2, 1]) is True
    assert logging_service._admin_list_changed([1, 2], [2, 1]) is False

    kinds = {
        "text": MessageType.TEXT,
        "photo": MessageType.PHOTO,
        "video": MessageType.VIDEO,
        "animation": MessageType.ANIMATION,
        "audio": MessageType.AUDIO,
        "voice": MessageType.VOICE,
        "document": MessageType.DOCUMENT,
        "sticker": MessageType.STICKER,
        "contact": MessageType.CONTACT,
        "location": MessageType.LOCATION,
        "venue": MessageType.VENUE,
        "video_note": MessageType.VIDEO_NOTE,
        "invoice": MessageType.INVOICE,
        "successful_payment": MessageType.SUCCESSFUL_PAYMENT,
        "game": MessageType.GAME,
        "poll": MessageType.POLL,
        "dice": MessageType.DICE,
        "new_chat_members": MessageType.NEW_CHAT_MEMBERS,
        "left_chat_member": MessageType.LEFT_CHAT_MEMBER,
        "new_chat_title": MessageType.NEW_CHAT_TITLE,
        "new_chat_photo": MessageType.NEW_CHAT_PHOTO,
        "delete_chat_photo": MessageType.DELETE_CHAT_PHOTO,
        "group_chat_created": MessageType.GROUP_CHAT_CREATED,
        "supergroup_chat_created": MessageType.SUPERGROUP_CHAT_CREATED,
        "channel_chat_created": MessageType.CHANNEL_CHAT_CREATED,
        "migrate_to_chat_id": MessageType.MIGRATE_TO_CHAT_ID,
        "migrate_from_chat_id": MessageType.MIGRATE_FROM_CHAT_ID,
        "pinned_message": MessageType.PINNED_MESSAGE,
        "connected_website": MessageType.CONNECTED_WEBSITE,
        "passport_data": MessageType.PASSPORT_DATA,
        "proximity_alert_triggered": MessageType.PROXIMITY_ALERT_TRIGGERED,
        "voice_chat_scheduled": MessageType.VOICE_CHAT_SCHEDULED,
        "voice_chat_started": MessageType.VOICE_CHAT_STARTED,
        "voice_chat_ended": MessageType.VOICE_CHAT_ENDED,
        "voice_chat_participants_invited": MessageType.VOICE_CHAT_PARTICIPANTS_INVITED,
        "message_auto_delete_timer_changed": MessageType.MESSAGE_AUTO_DELETE_TIMER_CHANGED,
    }
    for field, expected in kinds.items():
        if field == "text":
            value = "hello"
        elif field == "photo":
            value = [Bag(file_id="photo-id")]
        elif field == "new_chat_members":
            value = [make_user()]
        else:
            value = Bag(file_id=f"{field}-id")
        parsed = logging_service._parse_message(_message(**{field: value}))
        assert parsed.message_type is expected
    assert logging_service._detect_message_type(_message()) is MessageType.UNKNOWN

    photo = _message(photo=[Bag(file_id="p1")], caption="cap", reply_markup=Bag(to_dict=lambda: {"rows": []}))
    assert logging_service._extract_file_id(photo) == "p1"
    for field in ("video", "animation", "audio", "voice", "document", "sticker", "video_note"):
        assert logging_service._extract_file_id(_message(**{field: Bag(file_id=field)})) == field
    members = _message(new_chat_members=[make_user(full_name="甲"), make_user(full_name="")])
    assert "New members" in logging_service._parse_message(members).text
    left = _message(left_chat_member=make_user(full_name="乙"))
    assert "Left member" in logging_service._parse_message(left).text
    titled = _message(new_chat_title="新群")
    assert "新群" in logging_service._parse_message(titled).text
    pinned = _message(pinned_message=_message(text="被钉"))
    assert "Pinned" in logging_service._parse_message(pinned).text

    user = User(id=3)
    logging_service._sync_user_profile(user, make_user(3, username="@Ada", full_name="Ada"))
    assert user.username == "ada"
    logging_service._sync_user_profile(user, make_user(3, username="@Ada", full_name="Ada"))
    group = Group(id=8, name="旧", admin_ids=[1])
    logging_service._sync_group_profile(group, Bag(id=8, title="新"), [2])
    assert group.name == "新"
    assert group.admin_ids == [2]
    logging_service._sync_group_profile(group, Bag(id=8, title=""), None)

    monkeypatch.setattr(logging_service, "get_cached_admin_ids", AsyncMock(return_value=None))
    assert await logging_service._get_admin_ids(make_context(), 8) is None
    monkeypatch.setattr(logging_service, "get_cached_admin_ids", AsyncMock(return_value=[3]))

    update = make_update()
    update.effective_message = None
    await logging_service.log_message_update(update, make_context())
    migrating = make_update(chat_type="group", chat_id=8, user_id=3)
    migrating.effective_message.migrate_to_chat_id = 99
    await logging_service.log_message_update(migrating, make_context())

    group_message = _message(text="群消息")
    group_update = Bag(
        effective_message=group_message,
        effective_chat=Bag(id=-100, type="supergroup", title="群"),
        effective_user=make_user(3, username="ada", full_name="Ada", is_bot=False),
    )
    await logging_service.log_message_update(group_update, make_context())
    renamed = make_user(3, username="ada2", full_name="Ada Two", is_bot=True)
    group_update.effective_user = renamed
    group_message.message_id = 2
    await logging_service.log_message_update(group_update, make_context())

    private_message = _message(text="私聊", message_id=3)
    private_update = Bag(
        effective_message=private_message,
        effective_chat=Bag(id=3, type=Chat.PRIVATE, title=None),
        effective_user=make_user(4, username=None, full_name="私"),
    )
    await logging_service.log_message_update(private_update, make_context())
    private_message.message_id = 4
    await logging_service.log_message_update(private_update, make_context())

    channel = Bag(
        effective_message=_message(text="频道"),
        effective_chat=Bag(id=5, type="channel", title="c"),
        effective_user=make_user(5),
    )
    await logging_service.log_message_update(channel, make_context())


async def test_file_cache_and_image_resolvers(monkeypatch, tmp_path):
    import importlib

    files = importlib.import_module("services.file_service.get_file")
    from services.image_service import get_image as images

    files.reset_local_storage_root()
    monkeypatch.setattr(files, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(files.config_registry, "get_local_storage_config", AsyncMock(side_effect=RuntimeError("no")))
    assert await files._get_local_storage_root() is None
    files.reset_local_storage_root()
    monkeypatch.setattr(
        files.config_registry,
        "get_local_storage_config",
        AsyncMock(return_value=LocalStorageConfig(root_path="relative-storage")),
    )
    root = await files._get_local_storage_root()
    assert root is not None
    assert await files._get_local_storage_root() == root
    files.reset_local_storage_root()
    monkeypatch.setattr(
        files.config_registry,
        "get_local_storage_config",
        AsyncMock(return_value=LocalStorageConfig(root_path=str(tmp_path))),
    )

    with pytest.raises(FileNotFoundError):
        await files._ensure_cached_file("missing.bin", None)
    cached = tmp_path / "ready.bin"
    cached.write_bytes(b"ready")
    assert await files._ensure_cached_file("ready.bin", None) == cached
    monkeypatch.setattr(files, "download_file", AsyncMock(side_effect=FileExistsError("exists")))
    assert (await files._ensure_cached_file("remote.bin", "https://example/a.bin", refresh=True)).name == "remote.bin"
    with pytest.raises(ValueError):
        await files._ensure_cached_file("bad.bin", "ftp://example/a.bin", refresh=True)
    source = tmp_path / "source.bin"
    source.write_bytes(b"local-bytes")
    copied = await files._ensure_cached_file("copied.bin", str(source), refresh=True)
    assert copied.read_bytes() == b"local-bytes"
    relative = tmp_path / "rel.bin"
    relative.write_bytes(b"rel")
    assert (await files._ensure_cached_file("from-rel.bin", "rel.bin", refresh=True)).read_bytes() == b"rel"
    with pytest.raises(FileNotFoundError):
        await files._ensure_cached_file("gone.bin", "file:///tmp/does-not-exist-acgimg.bin", refresh=True)
    assert await files.get_file("copied.bin") == b"local-bytes"
    assert await files.get_image("copied.bin") == b"local-bytes"

    for mode in ("RGBA", "RGB", "L", "P", "CMYK"):
        image = Image.new(mode, (2, 2))
        prepared = files._prepare_for_webp(image)
        assert prepared.mode == "RGBA"
        prepared.close()
        image.close()
    raw = tmp_path / "tiny.png"
    Image.new("RGB", (2, 2), "red").save(raw)
    compressed = Path(files.compress_image(str(raw)))
    assert compressed.suffix == ".webp"
    with pytest.raises(Exception):
        files.compress_image(str(raw), target_size_mb=0, quality=30)

    illust = SimpleNamespace(
        id=7,
        page_count=2,
        file_urls=["https://a/0.jpg", ""],
        origin_urls=["https://o/0.jpg", "https://o/1.jpg"],
        file_ext=["png", "jpeg"],
        compressed_file_ids=[" id ", ""],
        original_file_ids=("orig",),
    )
    assert images._resolve_page_id(illust, None, False) == 0
    assert images._resolve_page_id(illust, 1, False) == 1
    with pytest.raises(FileNotFoundError):
        images._resolve_page_id(SimpleNamespace(page_count=0), None, True)
    from exps import BadRequestError

    with pytest.raises(BadRequestError):
        images._resolve_page_id(illust, 5, False)
    assert images._resolve_link(illust, 0) == "https://a/0.jpg"
    assert images._resolve_link(illust, 1) == "https://o/1.jpg"
    string_illust = SimpleNamespace(file_urls="https://only", origin_urls="https://origin", file_ext=("skip", "gif"), page_count=1)
    assert images._resolve_link(string_illust, 0) == "https://only"
    assert images._resolve_extension(string_illust, 0, "https://only") == ".gif"
    assert images._resolve_extension(SimpleNamespace(file_ext=None), 0, "https://a/b") == ".jpg"
    assert images._resolve_extension(SimpleNamespace(file_ext="png"), 0, "https://a/b.png") == ".png"
    assert images._resolve_file_id(illust, 0, origin=False) == "id"
    assert images._resolve_file_id(illust, 1, origin=False) is None
    assert images._resolve_file_id(illust, 0, origin=True) == "orig"
    assert images._resolve_file_id(SimpleNamespace(compressed_file_ids=" plain "), 0, origin=False) == "plain"
    assert images._resolve_file_id(SimpleNamespace(compressed_file_ids=123), 0, origin=False) is None
    assert images._resolve_file_id(SimpleNamespace(compressed_file_ids={"a", "b"}), 5, origin=False) is None

    monkeypatch.setattr(images.registries, "get_illust_info", AsyncMock(return_value=None))
    with pytest.raises(FileNotFoundError):
        await images.get_image_resource(pixiv_id=1)
    monkeypatch.setattr(images.registries, "get_illust_info", AsyncMock(return_value=illust))
    resource = await images.get_image_resource(pixiv_id=7, page_id=0, origin=True)
    assert resource.is_original is True
    assert resource.filename.endswith(".png")
    with pytest.raises(BadRequestError):
        await images.get_image_resource(origin=True)
    monkeypatch.setattr(images.registries, "random_illust", AsyncMock(return_value=None))
    with pytest.raises(FileNotFoundError):
        await images.get_image_resource()
    monkeypatch.setattr(images.registries, "random_illust", AsyncMock(return_value=illust))
    random_resource = await images.get_image_resource(allow_r18g=True)
    assert random_resource.page_id in {0, 1}
    direct = images.resource_for_illustration(illust, 1)
    assert direct.link == "https://o/1.jpg"
    empty_urls = SimpleNamespace(file_urls=[], origin_urls=[], page_count=1, file_ext=None, id=1, compressed_file_ids=None)
    with pytest.raises(FileNotFoundError):
        images._resolve_link(empty_urls, 0)


async def test_pixiv_service_without_network(monkeypatch):
    from services import pixiv_service as module

    assert module._error_text(None) == ""
    assert module._error_text("Not Found") == "Not Found"
    assert "missing" in module._error_text(RuntimeError("missing"))
    assert module._error_text({"a": ["不存在"]}) 
    assert module._is_missing_work({"message": "work does not exist"}) is True
    assert module._is_missing_work("ok") is False
    assert module._error_text(object())

    service = module.PixivService()
    monkeypatch.setattr(
        module.config_registry,
        "get_pixiv_tokens",
        AsyncMock(
            return_value=[
                Token(token="  ", enable=True, id=1),
                Token(token="refresh", enable=True, id=2),
                Token(token="off", enable=False, id=3),
                Token(token="skip", enable=True, id=None),
            ]
        ),
    )
    await service.read_token_from_config()
    assert service.enabled is True
    token = service._tokens[0]
    token.client.auth = Mock(return_value={"expires_in": 120})
    await service._refresh_token(token)
    await service._refresh_token(token)
    token.client.auth = Mock(side_effect=module.PixivError("bad"))
    with pytest.raises(module.PixivError):
        await service._refresh_token(token, force=True)
    token.client.auth = Mock(side_effect=RuntimeError("down"))
    with pytest.raises(RuntimeError):
        await service._refresh_token(token, force=True)

    token.client.auth = Mock(return_value={"expires_in": 0})
    token.client.illust_detail = Mock(return_value={"illust": {"id": 1}})
    detail = await service.get_raw(1)
    assert detail["illust"]["id"] == 1

    token.client.illust_detail = Mock(return_value={"error": "not found"})
    with pytest.raises(module.PixivWorkNotFound):
        await service._fetch_illust_detail(2)
    token.client.illust_detail = Mock(side_effect=[module.PixivError("temporary"), {"illust": {"id": 3}}])
    token.client.auth = Mock(return_value={"expires_in": 90})
    # A single token that fails the API call is not retried inside the same token
    # unless the payload itself contains an error. Use the error-retry branch.
    token.client.illust_detail = Mock(side_effect=[{"error": "rate"}, {"illust": {"id": 3}}])
    assert (await service._fetch_illust_detail(3))["illust"]["id"] == 3
    token.client.illust_detail = Mock(return_value="nope")
    with pytest.raises(RuntimeError):
        await service._fetch_illust_detail(4)
    token.enabled = False
    with pytest.raises(RuntimeError):
        await service._ordered_tokens()
    await service.token_refresh()

    monkeypatch.setattr(module.config_registry, "get_pixiv_tokens", AsyncMock(return_value=[]))
    await service.read_token_from_config()
    assert service.enabled is False
    await service.token_refresh(force=True)
    monkeypatch.setattr(module, "build_illust_from_api_dict", lambda data: SimpleNamespace(**data))
    service2 = module.PixivService()
    monkeypatch.setattr(
        module.config_registry,
        "get_pixiv_tokens",
        AsyncMock(return_value=[Token(token="refresh", enable=True, id=8)]),
    )
    await service2.read_token_from_config()
    service2._tokens[0].client.auth = Mock(return_value={"expires_in": 100})
    service2._tokens[0].client.illust_detail = Mock(return_value={"illust": {"id": 9}})
    info = await service2.get_illust_info_by_pixiv_id(9)
    assert info.id == 9
    service2._tokens[0].client.illust_detail = Mock(return_value={"illust": None})
    with pytest.raises(module.PixivWorkNotFound):
        await service2.get_illust_info_by_pixiv_id(9)
    service2._tokens[0].client.illust_detail = Mock(return_value={"error": "still bad"})
    service2._tokens[0].client.auth = Mock(side_effect=RuntimeError("refresh failed"))
    with pytest.raises(RuntimeError):
        await service2.get_illust_info_by_pixiv_id(9)


async def test_frontend_launcher_lifecycle(monkeypatch, tmp_path):
    from utils import frontend_launcher as launcher

    monkeypatch.setenv("AUTO_START_FRONTEND", "off")
    assert launcher.auto_start_enabled() is False
    monkeypatch.setenv("AUTO_START_FRONTEND", "1")
    assert launcher.auto_start_enabled() is True
    assert launcher.should_start_frontend_dev_server(static_build_exists=False) is True
    monkeypatch.setenv("AUTO_START_FRONTEND", "0")
    assert launcher.should_start_frontend_dev_server(static_build_exists=False) is False
    monkeypatch.setenv("AUTO_START_FRONTEND", "1")
    assert launcher.should_start_frontend_dev_server(static_build_exists=True, argv=["bot"]) is False
    assert launcher.should_start_frontend_dev_server(static_build_exists=True, argv=["bot", "--log-level=debug"]) is True
    assert launcher.should_start_frontend_dev_server(static_build_exists=True, argv=["bot", "--log-level", "debug"]) is True
    assert launcher.should_start_frontend_dev_server(static_build_exists=True, argv=["bot", "--log-level", "info"]) is False

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    assert launcher._build_command()[0] == "cmd"
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    assert launcher._build_command()[0] == "npm"

    launcher._dev_server = None
    monkeypatch.setattr(launcher, "WEBUI_DIR", tmp_path / "missing")
    assert await launcher.start_frontend_dev_server() is False

    webui = tmp_path / "webui"
    webui.mkdir()
    monkeypatch.setattr(launcher, "WEBUI_DIR", webui)

    class Proc:
        def __init__(self):
            self.pid = 321
            self.returncode = None
            self.stdout = self
            self._lines = [b"\x1b[32mready\x1b[0m\n", b""]

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        async def wait(self):
            while self.returncode is None:
                await asyncio.sleep(0.01)
            return self.returncode

        def poll(self):
            return self.returncode

    proc = Proc()
    monkeypatch.setattr(launcher.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    assert await launcher.start_frontend_dev_server() is True
    assert await launcher.start_frontend_dev_server() is True
    await asyncio.sleep(0)
    await launcher.stop_frontend_dev_server()
    await launcher.stop_frontend_dev_server()

    failed = Proc()
    failed.wait = AsyncMock(return_value=1)
    failed.returncode = 1
    monkeypatch.setattr(launcher.asyncio, "create_subprocess_exec", AsyncMock(return_value=failed))
    launcher._dev_server = None
    assert await launcher.start_frontend_dev_server() is True
    await asyncio.sleep(0)
    launcher._dev_server = None

    monkeypatch.setattr(launcher.asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError("npm")))
    assert await launcher.start_frontend_dev_server() is False
    monkeypatch.setattr(launcher.asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError("boom")))
    assert await launcher.start_frontend_dev_server() is False

    class Hanging(Proc):
        async def wait(self):
            await asyncio.sleep(30)

    hanging = Hanging()
    hanging.returncode = None
    launcher._dev_server = hanging
    await launcher.stop_frontend_dev_server()
    assert hanging.returncode == -9 or hanging.returncode == 0


async def test_registries_and_group_guard_sqlite():
    from datetime import datetime, timedelta, timezone

    from registries import active_message_handler_registry, command_history_registry, group_registry, user_registry
    from services import group_guard

    group_guard._settings_cache.clear()
    group_guard._keyword_cache.clear()

    assert user_registry.normalize_username("  @Ada ") == "ada"
    assert user_registry.normalize_username("   ") is None
    created = await user_registry.get_user_by_id(15)
    assert created.id == 15
    again = await user_registry.get_user_by_id(15)
    assert again.id == 15
    await user_registry.add_user(User(id=16, username="old"))
    await user_registry.sync_telegram_user(17, "@New")
    await user_registry.sync_telegram_user(17, "@New")
    await user_registry.sync_telegram_user(16, "changed")
    assert await user_registry.find_user_ids_by_username("@") == []
    matches = await user_registry.find_user_ids_by_username("@New")
    assert 17 in matches
    await user_registry.set_sanity_limit(15, 7)
    await user_registry.set_allow_r18g(15, True)
    await user_registry.set_status(15, UserStatus.INACTIVE)
    await user_registry.set_enable_chat(15, True)
    await user_registry.set_nick_name(15, "  " + "名" * 80)
    await user_registry.set_nick_name(15, "   ")

    group = await group_registry.get_group_by_id(21)
    assert group.id == 21
    assert (await group_registry.get_group_by_id(21)).id == 21
    await group_registry.add_group(Group(id=22))
    await group_registry.set_group_enable(22, False)
    await group_registry.set_group_sanity_limit(22, 4)
    await group_registry.set_group_allow_setu(22, False)

    when = datetime(2026, 2, 1, tzinfo=timezone.utc)
    await command_history_registry.record_command_execution(
        command="guard",
        user_id=15,
        chat_id=21,
        chat_type="group",
        message_id=1,
        arguments=["status"],
        raw_text="/guard status",
        success=True,
        error_message=None,
        duration_ms=3,
        triggered_at=when,
    )
    await command_history_registry.record_command_execution(
        command="setu",
        user_id=16,
        chat_id=None,
        chat_type=None,
        message_id=None,
        arguments=None,
        raw_text=None,
        success=False,
        error_message="x",
        duration_ms=None,
        triggered_at=when,
    )
    total, rows = await command_history_registry.query_history(command="guard", user_id=15, success=True, sort_order="asc")
    assert total == 1
    assert rows[0].command == "guard"
    total, _rows = await command_history_registry.query_history()
    assert total == 2

    assert await active_message_handler_registry.get(15) is None
    await active_message_handler_registry.set(15, handler_id="set_cache_ttl:1")
    await active_message_handler_registry.set(15, handler_id="set_cache_ttl:2")
    assert await active_message_handler_registry.get(15) == "set_cache_ttl:2"
    await active_message_handler_registry.delete(15)
    assert await active_message_handler_registry.get(15) is None

    settings = await group_guard.get_guard_settings(30)
    assert settings.verification_timeout == 60
    cached = await group_guard.get_guard_settings(30)
    assert cached.group_id == 30
    updated = await group_guard.set_verification_enabled(30, True)
    assert updated.verification_enabled is True
    assert (await group_guard.set_verification_timeout(30, 1)).verification_timeout == 15
    assert (await group_guard.set_verification_timeout(30, 99999)).verification_timeout == 3600
    with pytest.raises(ValueError):
        await group_guard.set_verification_message(30, "x" * 5000)
    cleared = await group_guard.set_verification_message(30, "  hi  ")
    assert cleared.verification_message == "hi"
    assert (await group_guard.set_verification_message(30, None)).verification_message is None
    assert (await group_guard.set_kick_on_timeout(30, False)).kick_on_timeout is False
    assert (await group_guard.set_keyword_filter_enabled(30, True)).keyword_filter_enabled is True
    assert await group_guard.list_keyword_rules(30) == []
    with pytest.raises(ValueError):
        await group_guard.add_keyword_rule(30, "   ")
    with pytest.raises(ValueError):
        await group_guard.add_keyword_rule(30, "x" * 600)
    with pytest.raises(ValueError):
        await group_guard.add_keyword_rule(30, "(", is_regex=True)
    rule = await group_guard.add_keyword_rule(30, "spam", is_regex=True, case_sensitive=True)
    assert rule.is_regex is True
    assert len(await group_guard.list_keyword_rules(30)) == 1
    assert len(await group_guard.list_keyword_rules(30)) == 1
    assert await group_guard.remove_keyword_rule(30, 99999) is False
    assert await group_guard.remove_keyword_rule(30, rule.id) is True
    await group_guard.add_keyword_rule(30, "other")
    assert await group_guard.clear_keyword_rules(30) == 1

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    pending = await group_guard.upsert_pending_verification(
        group_id=30, user_id=15, message_id=1, token="tok", expires_at=future.replace(tzinfo=None)
    )
    assert pending.is_expired(now=future + timedelta(seconds=1)) is True
    assert pending.is_expired(now=past) is False
    again_pending = await group_guard.upsert_pending_verification(
        group_id=30, user_id=15, message_id=2, token="tok2", expires_at=future
    )
    assert again_pending.message_id == 2
    assert (await group_guard.get_pending_verification(30, 15)).token == "tok2"
    assert await group_guard.get_pending_verification(30, 99) is None
    assert (await group_guard.get_pending_verification_by_token("tok2")).user_id == 15
    assert await group_guard.get_pending_verification_by_token("missing") is None
    assert await group_guard.cleanup_expired_pending(future + timedelta(days=1)) >= 1
    await group_guard.delete_pending_verification(30, 15)
    await group_guard.ensure_settings([])
    await group_guard.ensure_settings([0, 31, 31])
    await group_guard.ensure_settings([31])
    assert len(group_guard.generate_token(8)) == 8
    assert group_guard.operation_lock(30) is group_guard.operation_lock(30)


def test_image_push_pure_helpers():
    from services import image_push

    assert image_push.normalize_pid_spec(" 42 ") == "42"
    assert image_push.normalize_pid_spec("42:2") == "42:2"
    with pytest.raises(ValueError):
        image_push.parse_pid_spec("0")
    with pytest.raises(ValueError):
        image_push.parse_pid_spec(None)
    aware = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert image_push.to_utc_naive(aware).tzinfo is None
    with pytest.raises(ValueError):
        image_push.to_utc_naive(datetime(2026, 1, 1))
    clock = datetime(2026, 1, 1, 0, 0)
    nxt = image_push.next_occurrence(clock, "interval", "UTC", interval_seconds=60, clock=clock)
    assert nxt > clock
    with pytest.raises(ValueError):
        image_push.next_occurrence(clock, "interval", "UTC", interval_seconds=None, clock=clock)
    weekly = image_push.next_occurrence(aware, "weekly", "Asia/Shanghai", clock=aware.replace(tzinfo=None))
    assert weekly > aware.replace(tzinfo=None)
    assert image_push.group_push_block_reason(None) == "群组不存在或已删除"
    blocked = SimpleNamespace(status=GroupStatus.BLOCKED, enable=True, allow_setu=True)
    assert "阻塞" in image_push.group_push_block_reason(blocked)
    disabled = SimpleNamespace(status="disabled", enable=True, allow_setu=True)
    assert "停用" in image_push.group_push_block_reason(disabled)
    closed = SimpleNamespace(status=GroupStatus.ENABLED, enable=True, allow_setu=False)
    assert "关闭" in image_push.group_push_block_reason(closed)
    assert image_push.group_push_block_reason(SimpleNamespace(status=GroupStatus.ENABLED, enable=True, allow_setu=True)) is None
    illust = SimpleNamespace(page_count=2, id=5, source_type="manual", title="t", author_name=None, author_id=1, is_ai=True)
    with pytest.raises(ValueError):
        image_push._page_index(SimpleNamespace(page_count=0), None)
    with pytest.raises(ValueError):
        image_push._page_index(illust, 9)
    assert image_push._page_index(illust, 2) == 1
    assert image_push._page_index(illust, None) in {0, 1}
    assert image_push._pixiv_metadata_lines(illust) == []
    pixiv = SimpleNamespace(page_count=1, id=5, source_type="pixiv", title="", author_name="a", author_id=2, is_ai=False)
    assert "PID" in image_push._caption(pixiv, 0)
    assert image_push._with_pixiv_metadata("cap", illust) == "cap"
    assert "PID" in image_push._with_pixiv_metadata("cap", pixiv)
    snapshot = image_push._config_snapshot({"target_scope": "all", "group_ids": None, "mode": "random", "pid": "8", "pid_by_group": {1: "9:2"}})
    assert snapshot["pid"] == "8"
    assert snapshot["pid_by_group"]["1"] == "9:2"


async def test_bot_can_send_photo(monkeypatch):
    from telegram.error import TelegramError

    from services import image_push

    assert await image_push._bot_can_send_photo(SimpleNamespace(), 1) == (True, None)
    bot = SimpleNamespace(id=2, get_chat_member=AsyncMock(side_effect=TelegramError("no")), get_chat=AsyncMock())
    allowed, reason = await image_push._bot_can_send_photo(bot, 1)
    assert allowed is False and reason
    bot.get_chat_member = AsyncMock(side_effect=RuntimeError("down"))
    assert (await image_push._bot_can_send_photo(bot, 1))[0] is False
    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="kicked", can_send_messages=True, can_send_photos=True))
    assert "移出" in (await image_push._bot_can_send_photo(bot, 1))[1]
    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="administrator", can_send_photos=False, can_send_messages=True))
    assert (await image_push._bot_can_send_photo(bot, 1))[0] is False
    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member", can_send_messages=None, can_send_photos=None))
    bot.get_chat = AsyncMock(side_effect=TelegramError("chat"))
    assert (await image_push._bot_can_send_photo(bot, 1))[0] is False
    bot.get_chat = AsyncMock(side_effect=RuntimeError("chat"))
    assert (await image_push._bot_can_send_photo(bot, 1))[0] is False
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=SimpleNamespace(can_send_messages=False, can_send_photos=True)))
    assert (await image_push._bot_can_send_photo(bot, 1))[0] is False
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=None))
    assert await image_push._bot_can_send_photo(bot, 1) == (True, None)
