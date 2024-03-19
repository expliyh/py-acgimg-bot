import logging
import time

from pixivpy3 import *
from registries import config_registry

from models import Illustration

logger = logging.getLogger(__name__)


class PixivService:
    def __init__(self):
        self.valid_until: int | None = None
        self.token: str | None = None
        self.api = AppPixivAPI()

    async def read_token_from_config(self):
        tokens = await config_registry.get_pixiv_tokens()
        if len(tokens) > 1:
            raise Exception("More than one Pixiv token found")
        self.token = tokens[0]
        self.valid_until = 0

    def token_refresh(self, force: bool = False):
        if self.token is None:
            raise Exception("Pixiv token not found")
        if not force and self.valid_until > int(time.time()):
            return
        response = self.api.auth(refresh_token=self.token)
        self.valid_until = int(time.time()) + int(response["expires_in"]) - 60
        logger.info("已刷新PixivAccessToken")
        return

    async def get_raw(self, pixiv_id: int):
        self.token_refresh()
        response = self.api.illust_detail(pixiv_id)
        if response.get("error") is not None:
            self.token_refresh(force=True)
        response = self.api.illust_detail(pixiv_id)
        return response

    async def get_illust_info_by_pixiv_id(self, pixiv_id: int) -> Illustration:
        self.token_refresh()
        if self.token is None:
            raise Exception("Pixiv token not found")
        illust_info = None
        if not force_refresh:
            illust_info = self.__cache.get_cache_by_pixiv_id(pixiv_id)
        if illust_info is None:
            illust_info = CachedIllustDetail(await database.get_illust_info_by_pixiv_id(pixiv_id))
            try:
                illust_info.pixiv_id = illust_info.pixiv_id
                self.__cache.update_cache(await database.get_illust_info_by_pixiv_id(pixiv_id))
            except AttributeError as ex:
                illust_info = None
                pass
        if illust_info is None:
            illust_info_dict: dict = self.__api.illust_detail(pixiv_id)
            db_illust_info = IllustInfo(illust_info_dict)
            self.__cache.update_cache(db_illust_info)
            illust_info = CachedIllustDetail(db_illust_info)
        else:
            pass
        return illust_info
