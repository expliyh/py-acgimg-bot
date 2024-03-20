from abc import abstractmethod

from fastapi import UploadFile


class Storage:
    @abstractmethod
    async def get_config(self):
        pass

    @abstractmethod
    async def upload(self, file: bytes, filename: str, sub_folder: str) -> str:
        pass
