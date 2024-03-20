from b2sdk.v2 import InMemoryAccountInfo, B2Api, FileVersion, Bucket
from fastapi import UploadFile

from registries import config_registry
from .Storage import Storage


class BackBlaze(Storage):
    async def upload(self, file: bytes, filename: str, sub_folder: str | None = None) -> str:
        if sub_folder is None:
            sub_folder = ""
        else:
            while sub_folder.startswith("/"):
                sub_folder = sub_folder[1:]
            if not sub_folder.endswith("/"):
                sub_folder += "/"
        info = {
            "msg": "Automatic upload by py-acgimg-bot"
        }
        file_version: FileVersion = self.bucket.upload_bytes(
            data_bytes=file,
            file_name=self.base_path + sub_folder + filename,
            file_info=info
        )
        assert file_version is not None
        url = self.base_url + "/" + self.base_path + sub_folder + filename
        return url

    def __init__(self):
        self.info = InMemoryAccountInfo()
        self.b2_api = B2Api(self.info)
        self.app_id: str | None = None
        self.app_key: str | None = None
        self.bucket_name: str | None = None
        self.bucket: Bucket | None = None
        self.base_path: str | None = None
        self.base_url: str | None = None

    async def get_config(self):
        config = await config_registry.get_backblaze_config()
        self.app_id = config.app_id
        self.app_key = config.app_key
        self.bucket_name = config.bucket_name
        self.base_path = config.base_path
        self.base_url = config.base_url
        self.b2_api.authorize_account("production", self.app_id, self.app_key)
        self.bucket = self.b2_api.get_bucket_by_name(self.bucket_name)
        return
