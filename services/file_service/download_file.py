import logging
import os
import uuid
from pathlib import Path

import aiofiles
import aiohttp

from . import file_lock
from .conf import file_path

logger = logging.getLogger(__name__)


async def download_file(filename: str, url: str, replace: bool = False):
    dict_lock, lock = file_lock.get_lock(filename)
    destination = Path(file_path) / filename
    async with dict_lock.reader_lock:
        async with lock:
            if destination.exists() and not replace:
                raise FileExistsError
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.part")
            try:
                retries = 5
                for attempt in range(1, retries + 1):
                    try:
                        timeout = aiohttp.ClientTimeout(total=10)
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            headers = {"Referer": "https://app-api.pixiv.net/"}
                            async with session.get(url, headers=headers) as response:
                                if response.status != 200:
                                    response.raise_for_status()
                                    raise aiohttp.ClientError(
                                        f"Unexpected download status: {response.status}"
                                    )
                                data = await response.content.read()
                                async with aiofiles.open(temporary, "wb") as file:
                                    await file.write(data)
                        os.replace(temporary, destination)
                        return
                    except (aiohttp.ClientError, TimeoutError):
                        logger.debug("Download attempt %s/%s failed", attempt, retries, exc_info=True)
                        if attempt == retries:
                            raise
            finally:
                temporary.unlink(missing_ok=True)
