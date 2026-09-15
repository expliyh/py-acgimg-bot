"""Safe read/delete access to files referenced by stored illustrations.

The storage providers historically exposed upload-only URLs.  Gallery media
must work for the default relative local URLs as well as for configured remote
providers, without turning the API into an arbitrary URL proxy.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import aiohttp
from aiohttp import BasicAuth

from registries import config_registry
from services.storage_service.backblaze import backblaze


MAX_MEDIA_BYTES = 20 * 1024 * 1024
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


class MediaAccessError(RuntimeError):
    """The URL is known but cannot be read or removed safely."""


@dataclass(slots=True)
class MediaContent:
    data: bytes
    media_type: str


def _media_type(url: str) -> str:
    guessed, _ = mimetypes.guess_type(urlsplit(url).path)
    return guessed if guessed and guessed.startswith("image/") else "application/octet-stream"


def _base_matches(url: str, base: str | None) -> bool:
    if not base:
        return False
    try:
        target = urlsplit(url)
        root = urlsplit(base)
        target_port = target.port
        root_port = root.port
    except ValueError:
        return False
    if (
        target.scheme.lower() not in {"http", "https"}
        or root.scheme.lower() not in {"http", "https"}
        or target.username is not None
        or target.password is not None
        or target.scheme.lower() != root.scheme.lower()
        or (target.hostname or "").lower() != (root.hostname or "").lower()
    ):
        return False
    if (target_port or _default_port(target.scheme)) != (root_port or _default_port(root.scheme)):
        return False
    root_path = root.path.rstrip("/")
    return target.path == root_path or target.path.startswith(f"{root_path}/")


def _default_port(scheme: str) -> int | None:
    return 443 if scheme.lower() == "https" else 80 if scheme.lower() == "http" else None


def _relative_url_path(url: str, base: str) -> str:
    target = urlsplit(url)
    root = urlsplit(base)
    root_path = root.path.rstrip("/")
    relative = target.path[len(root_path) :].lstrip("/")
    return _safe_relative_name(relative)


def _safe_relative_name(value: str) -> str:
    decoded = unquote(value).replace("\\", "/").strip("/")
    if "\x00" in decoded:
        raise MediaAccessError("图片路径无效")
    segments = decoded.split("/") if decoded else []
    if not segments:
        raise MediaAccessError("图片路径为空")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise MediaAccessError("图片路径包含非法片段")
    # A colon in a Windows path segment can address an alternate data stream
    # (for example ``image.jpg:secret``), which is outside the intended media
    # object even though it remains below the configured directory.
    if os.name == "nt" and any(":" in segment for segment in segments):
        raise MediaAccessError("图片路径包含非法片段")
    return "/".join(segments)


def _local_root(root_value: str | None) -> Path:
    root = Path(root_value or "storage").expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def _safe_local_path(root: Path, relative: str) -> Path:
    candidate = (root / relative.replace("\\", "/")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise MediaAccessError("图片路径超出存储目录") from exc
    return candidate


def _absolute_local_relative(root: Path, value: str) -> str:
    """Convert an absolute local reference to a root-relative safe name."""

    decoded = unquote(value).replace("\\", "/")
    raw_segments = decoded.strip("/").split("/") if decoded.strip("/") else []
    if any(segment in {"", ".", ".."} for segment in raw_segments):
        raise MediaAccessError("图片路径包含非法片段")
    candidate = Path(decoded).expanduser().resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise MediaAccessError("图片路径超出存储目录") from exc
    return _safe_relative_name(relative.as_posix())


def _local_relative_reference(url: str, config: Any) -> str:
    """Resolve relative, file://, and absolute local references safely."""

    raw = url.strip()
    root = _local_root(config.root_path)
    if _WINDOWS_DRIVE_PATH.match(raw):
        return _absolute_local_relative(root, raw)
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise MediaAccessError("图片 URL 无效") from exc
    scheme = parsed.scheme.lower()
    if parsed.netloc:
        raise MediaAccessError("图片 URL 不属于本地存储")
    path = parsed.path
    if scheme == "file":
        drive_path = path.lstrip("/")
        if _WINDOWS_DRIVE_PATH.match(drive_path):
            return _absolute_local_relative(root, drive_path)
        candidate = Path(unquote(path)).expanduser()
        if candidate.is_absolute():
            return _absolute_local_relative(root, unquote(path))
    elif scheme:
        raise MediaAccessError("图片 URL 不属于本地存储")
    # On POSIX a leading slash is an absolute filesystem reference.  Local
    # storage uploads themselves use root-relative names, so treating this
    # form as absolute avoids accidentally mapping an outside path below the
    # configured root while retaining the established Windows behavior.
    elif os.name != "nt" and path.startswith("/"):
        return _absolute_local_relative(root, unquote(path))
    return _safe_relative_name(path)


async def _read_http(url: str, *, auth: BasicAuth | None = None) -> MediaContent:
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(auth=auth, timeout=timeout) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status == 404:
                    raise FileNotFoundError(url)
                if response.status < 200 or response.status >= 300:
                    raise MediaAccessError(f"远程图片读取失败：HTTP {response.status}")
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > MAX_MEDIA_BYTES:
                            raise MediaAccessError("图片超过允许的大小")
                    except ValueError as exc:
                        raise MediaAccessError("远程图片返回了无效的文件大小") from exc
                data = await response.content.read(MAX_MEDIA_BYTES + 1)
                if len(data) > MAX_MEDIA_BYTES:
                    raise MediaAccessError("图片超过允许的大小")
                response_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
                if response_type and not response_type.startswith("image/") and response_type not in {
                    "application/octet-stream",
                    "binary/octet-stream",
                }:
                    raise MediaAccessError(f"远程资源不是图片：{response_type}")
                media_type = response_type if response_type.startswith("image/") else _media_type(url)
                return MediaContent(data=data, media_type=media_type)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise MediaAccessError(f"远程图片读取失败：{exc}") from exc


async def _resolve_provider(url: str) -> tuple[str, Any]:
    """Resolve a stored URL against configured provider prefixes."""

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise MediaAccessError("图片 URL 无效") from exc
    scheme = parsed.scheme.lower()
    try:
        local = await config_registry.get_local_storage_config()
    except Exception as exc:
        raise MediaAccessError("读取本地存储配置失败") from exc
    if (
        _WINDOWS_DRIVE_PATH.match(url.strip())
        or (scheme in {"", "file"} and not parsed.netloc)
    ):
        relative = _local_relative_reference(url, local)
        return "local", (local, relative)
    if _base_matches(url, local.base_url):
        return "local", (local, _relative_url_path(url, local.base_url or ""))

    try:
        backblaze_config = await config_registry.get_backblaze_config()
    except Exception as exc:
        raise MediaAccessError("读取 Backblaze 存储配置失败") from exc
    if _base_matches(url, backblaze_config.base_url):
        return "backblaze", (backblaze_config, _relative_url_path(url, backblaze_config.base_url or ""))

    try:
        webdav_config = await config_registry.get_webdav_config()
    except Exception as exc:
        raise MediaAccessError("读取 WebDAV 存储配置失败") from exc
    if _base_matches(url, webdav_config.public_base_url):
        return "webdav", (webdav_config, _relative_url_path(url, webdav_config.public_base_url or ""))
    if _base_matches(url, webdav_config.endpoint):
        return "webdav", (webdav_config, _relative_url_path(url, webdav_config.endpoint or ""))

    raise MediaAccessError("图片 URL 不属于已配置的存储服务")


async def read_media_url(url: str) -> MediaContent:
    if not isinstance(url, str) or not url.strip():
        raise FileNotFoundError("没有可用的图片地址")
    provider, details = await _resolve_provider(url.strip())
    if provider == "local":
        config, relative = details
        path = _safe_local_path(_local_root(config.root_path), relative)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        if path.stat().st_size > MAX_MEDIA_BYTES:
            raise MediaAccessError("图片超过允许的大小")
        data = await asyncio.to_thread(path.read_bytes)
        if len(data) > MAX_MEDIA_BYTES:
            raise MediaAccessError("图片超过允许的大小")
        return MediaContent(data=data, media_type=_media_type(str(path)))
    if provider == "backblaze":
        # The configured base URL is required by the upload provider and is the
        # only host accepted here; no arbitrary URL is fetched.
        return await _read_http(url)

    config, relative = details
    base = config.endpoint
    if not base:
        raise MediaAccessError("WebDAV endpoint 未配置")
    remote_url = f"{base.rstrip('/')}/{quote(relative, safe='/')}" if relative else base
    auth = BasicAuth(config.username, config.password or "") if config.username else None
    return await _read_http(remote_url, auth=auth)


async def delete_media_url(url: str) -> None:
    """Delete one stored object; missing objects are treated as idempotent."""

    if not isinstance(url, str) or not url.strip():
        return
    provider, details = await _resolve_provider(url.strip())
    if provider == "local":
        config, relative = details
        path = _safe_local_path(_local_root(config.root_path), relative)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except FileNotFoundError:
            return
        return

    if provider == "backblaze":
        config, object_name = details
        del config  # The shared provider owns the authenticated bucket.
        try:
            await backblaze.ensure_ready()
            bucket = backblaze.bucket
            if bucket is None:
                raise MediaAccessError("Backblaze bucket 未配置")

            def remove_versions() -> None:
                versions = bucket.list_file_versions(file_name=object_name, fetch_count=100)
                for version in versions:
                    version.delete()

            await asyncio.to_thread(remove_versions)
        except FileNotFoundError:
            return
        except MediaAccessError:
            raise
        except Exception as exc:  # provider SDK errors are surfaced to caller
            raise MediaAccessError(f"Backblaze 文件清理失败：{exc}") from exc
        return

    config, relative = details
    endpoint = config.endpoint
    if not endpoint:
        raise MediaAccessError("WebDAV endpoint 未配置")
    remote_url = f"{endpoint.rstrip('/')}/{quote(relative, safe='/')}" if relative else endpoint
    auth = BasicAuth(config.username, config.password or "") if config.username else None
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(auth=auth, timeout=timeout) as session:
            async with session.delete(remote_url, allow_redirects=False) as response:
                if response.status in {404, 410}:
                    return
                if response.status < 200 or response.status >= 300:
                    raise MediaAccessError(f"WebDAV 文件清理失败：HTTP {response.status}")
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise MediaAccessError(f"WebDAV 文件清理失败：{exc}") from exc
