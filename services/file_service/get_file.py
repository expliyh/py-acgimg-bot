import os.path

from aiofiles import open

from . import file_lock
from .download_file import download_file
from .conf import file_path

from PIL import Image


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
    file_url = file_path + filename
    if not os.path.exists(file_url):
        await download_file(filename, url)
    if os.path.getsize(file_url) > 10000000:
        file_url = compress_image(file_url)
    dict_lock, lock = file_lock.get_lock(filename)
    async with dict_lock.reader_lock:
        async with lock:
            async with open(file_url, 'rb') as f:
                return await f.read()


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
