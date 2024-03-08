from models import Illustration

import registries
from services import file_service
import exceptions.BadRequestError


async def get_image(pixiv_id: int=None, page_id: int=None, origin: bool = False) -> tuple[Illustration, bytes]:
    if pixiv_id is not None:
        illust = await registries.get_illust_info(pixiv_id)
        if illust is None:
            raise FileNotFoundError(f'No such illust in database: {pixiv_id}')
        link = illust.file_urls[page_id]
        if origin:
            image = await file_service.get_file(
                filename=f"{pixiv_id}_{page_id}.{illust.file_ext}",
                url=link
            )
            return illust, image
        else:
            image = await file_service.get_image(
                filename=f"{pixiv_id}_{page_id}.{illust.file_ext}",
                url=link
            )
            return illust, image
    if origin:
        raise BadRequestError("Orign request is not supported when request a random image")

