import logging
import time

from pixivpy3 import *
from registries import config_registry

from models import Illustration, build_illust_from_api_dict

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
        self.token = tokens[0].token
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
        illust_info_dict: dict = self.api.illust_detail(pixiv_id)['illust']
        illust = build_illust_from_api_dict(illust_info_dict)
        return illust


pixiv = PixivService()
