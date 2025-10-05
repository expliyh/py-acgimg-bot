from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
from registries import config_registry

from . import file_lock
from .download_file import download_file
from .conf import file_path

from PIL import Image


CACHE_ROOT = Path(file_path).expanduser()
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


_LOCAL_STORAGE_ROOT: Path | None = None


async def _get_local_storage_root() -> Path | None:
    global _LOCAL_STORAGE_ROOT
    if _LOCAL_STORAGE_ROOT is not None:
        return _LOCAL_STORAGE_ROOT
    try:
        config = await config_registry.get_local_storage_config()
    except Exception:
        return None
    root_value = config.root_path or "storage"
    root_path = Path(root_value).expanduser()
    if not root_path.is_absolute():
        root_path = (Path.cwd() / root_path).resolve()
    else:
        root_path = root_path.resolve()
    _LOCAL_STORAGE_ROOT = root_path
    return _LOCAL_STORAGE_ROOT


async def _resolve_local_path(path: Path) -> Path:
    root = await _get_local_storage_root()
    if root is None:
        return path.resolve()
    return (root / path).resolve()


async def _copy_local_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(source, 'rb') as src, aiofiles.open(destination, 'wb') as dst:
        while True:
            chunk = await src.read(64 * 1024)
            if not chunk:
                break
            await dst.write(chunk)


async def _ensure_cached_file(filename: str, url: str | None) -> Path:
    cache_path = CACHE_ROOT / filename
    if cache_path.exists():
        return cache_path

    if url is None:
        raise FileNotFoundError("没有可用的文件来源")

    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        try:
            await download_file(filename, url)
        except FileExistsError:
            pass
        return cache_path

    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"不支持的文件来源协议: {parsed.scheme}")

    source_path = Path(parsed.path if parsed.scheme == "file" else url).expanduser()
    if not source_path.is_absolute():
        source_path = await _resolve_local_path(source_path)
    else:
        source_path = source_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"源文件不存在: {source_path}")

    dict_lock, lock = file_lock.get_lock(filename)
    async with dict_lock.reader_lock:
        async with lock:
            if cache_path.exists():
                return cache_path
            await _copy_local_file(source_path, cache_path)

    return cache_path

def _prepare_for_webp(image: Image.Image) -> Image.Image:
    """Return an RGBA copy ready for WebP encoding."""
    if image.mode == "RGBA":
        return image.copy()
    if image.mode == "RGB":
        return image.convert("RGBA")
    if image.mode in {"LA", "L"}:
        return image.convert("RGBA")
    if image.mode == "P":
        return image.convert("RGBA")
    if image.mode in {"CMYK", "YCbCr", "HSV", "LAB"}:
        return image.convert("RGBA")
    return image.convert("RGBA")


def compress_image(infile, target_size_mb=10, step=5, quality=95) -> str:
    """
    Compress an image to be within the target size in megabytes.

    The image will be re-encoded as WebP while attempting to meet the limit.

    :param infile: Input image file path
    :param target_size_mb: Target size in megabytes
    :param step: Step size for quality reduction
    :param quality: Starting quality for compression
    :return: str. Output image file path.
    """
    target_size = target_size_mb * 1024 * 1024

    with Image.open(infile) as original:
        img = _prepare_for_webp(original)

    outfile = os.path.splitext(infile)[0] + "_compressed.webp"

    try:
        while True:
            img.save(outfile, 'WEBP', quality=quality)

            if os.path.getsize(outfile) <= target_size:
                break

            quality -= step
            if quality < 30:
                raise Exception("Cannot compress the image enough to meet the target size.")
    finally:
        img.close()

    return outfile
    # print(f"Image compressed to {quality}% and saved as '{outfile}'")


async def get_image(filename: str, url: str = None) -> bytes | None:
    cache_path = await _ensure_cached_file(filename, url)
    dict_lock, lock = file_lock.get_lock(filename)
    async with dict_lock.reader_lock:
        async with lock:
            path_to_read = cache_path
            if path_to_read.exists() and path_to_read.stat().st_size > 10_000_000:
                path_to_read = Path(compress_image(str(path_to_read)))
            async with aiofiles.open(path_to_read, 'rb') as f:
                return await f.read()


async def get_file(filename: str, url: str = None) -> bytes | None:
    cache_path = await _ensure_cached_file(filename, url)
    dict_lock, lock = file_lock.get_lock(filename)
    async with dict_lock.reader_lock:
        async with lock:
            async with aiofiles.open(cache_path, 'rb') as f:
                return await f.read()
