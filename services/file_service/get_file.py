import os.path

from aiofiles import open

from . import file_lock
from .download_file import download_file
from .conf import file_path


async def get_file(filename: str, url: str = None) -> bytes | None:
    file_url = file_path + filename
    if not os.path.exists(file_url):
        await download_file(filename, url)
        # return None
    dict_lock, lock = file_lock.get_lock(filename)
    async with dict_lock.reader_lock:
        async with lock:
            async with open(file_url, 'rb') as f:
                return await f.read()
