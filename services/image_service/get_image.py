from models import Illustration

import registries
from services import file_service


async def get_image(pixiv_id: int, page_id: int, origin: bool = False) -> tuple[Illustration, bytes]:
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

    pass
