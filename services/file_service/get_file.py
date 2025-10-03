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


def compress_image(infile, target_size_mb=10, step=5, quality=95) -> str:
    """
    Compress an image to be within the target size in megabytes.

    :param infile: Input image file path
    :param target_size_mb: Target size in megabytes
    :param step: Step size for quality reduction
    :param quality: Starting quality for compression
    :return: str. Output image file path.
    """
    # 计算目标字节数
    target_size = target_size_mb * 1024 * 1024

    # 读取图片
    img = Image.open(infile)

    # 初始的临时文件名
    outfile = os.path.splitext(infile)[0] + "_compressed.jpg"

    # 循环直到图片大小小于目标大小
    while True:
        # Save the image with the current quality level
        img.save(outfile, 'JPEG', quality=quality)

        # Check the size of the output file
        if os.path.getsize(outfile) <= target_size:
            break  # 如果文件大小符合要求则退出循环

        # 否则减少图片质量
        quality -= step
        # 如果质量在某个阈值以下，不再继续减小
        if quality < 30:
            raise Exception("Cannot compress the image enough to meet the target size.")
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
