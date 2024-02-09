import asyncio
import os

import aiofiles
import aiohttp

from . import file_lock
from .conf import file_path


async def download_file(filename: str, url: str, replace: bool = False):
    dict_lock, lock = file_lock.get_lock(filename)
    file_url = file_path + filename
    async with dict_lock.reader_lock:
        async with lock:
            if os.path.exists(file_url):
                if not replace:
                    raise FileExistsError
                else:
                    os.remove(file_url)
            retries = 5
            attempt = 0
            while attempt < retries:
                try:
                    # 创建一个 ClientTimeout 对象
                    timeout_settings = aiohttp.ClientTimeout(total=10)
                    async with aiohttp.ClientSession(timeout=timeout_settings) as session:
                        async with session.get(url) as response:
                            if response.status == 200:
                                # 打开文件准备写入
                                with aiofiles.open(file_url, 'wb') as f:
                                    await f.write(await response.content.read())
                                return
                            else:
                                raise aiohttp.HttpProcessingError(
                                    message=f"Error {response.status} while downloading file.",
                                    code=response.status,
                                )
                except (aiohttp.ClientError, aiohttp.HttpProcessingError) as e:
                    print(f"Attempt {attempt} failed: {e}")
                    attempt += 1
                    if attempt >= retries:
                        try:
                            os.remove(file_url)
                        except FileNotFoundError as _:
                            pass
                        print(f"Failed to download file after {retries} attempts.")
                        raise e
