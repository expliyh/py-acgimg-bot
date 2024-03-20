from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Config
from .engine import engine


class Token:
    token: str
    enable: bool

    def __init__(self, token: str, enable: bool):
        self.token = token
        self.enable = enable


class BackBlazeConfig:
    app_id: str | None
    app_key: str | None
    bucket_name: str | None
    base_path: str | None
    base_url: str | None

    def set_app_id(self, app_id: str):
        self.app_id = app_id

    def set_app_key(self, app_key: str):
        self.app_key = app_key

    def set_bucket_name(self, bucket_name: str):
        self.bucket_name = bucket_name

    def set_base_path(self, base_path: str):
        if base_path is None:
            self.base_path = None
            return
        self.base_path = base_path
        if not self.base_path.endswith("/"):
            self.base_path += "/"
        while self.base_path.startswith("/"):
            self.base_path = self.base_path[1:]

    def set_base_url(self, base_url: str):
        if base_url is None:
            self.base_url = None
            return
        self.base_url = base_url
        while self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]

    def __init__(self,
                 app_id: str = None,
                 app_key: str = None,
                 bucket_name: str = None,
                 base_path: str = None,
                 base_url: str = None
                 ):
        self.app_id = app_id
        self.app_key = app_key
        self.bucket_name = bucket_name
        self.set_base_path(base_path)
        self.set_base_url(base_url)


async def get_configs(key: str) -> list[Config]:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(Config).where(Config.key == key))
        configs: list[Config] = []
        for row in result.scalars():
            row: Config = row
            configs.append(row)
        return configs


async def get_config(key: str) -> Config | None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(Config).where(Config.key == key))
        if result.scalar() is None:
            return None
        return result.scalar().first()


async def get_bot_tokens() -> list[Token]:
    result = await get_configs("bot_token")
    tokens: list[Token] = []
    for i in result:
        tokens.append(Token(i.value_str, i.value_bool))
    return tokens


async def get_pixiv_tokens() -> list[Token]:
    result = await get_configs("pixiv_token")
    tokens: list[Token] = []
    for i in result:
        tokens.append(Token(i.value_str, i.value_bool))
    return tokens


async def get_backblaze_config() -> BackBlazeConfig:
    config = BackBlazeConfig(
        app_id=(await get_config("backblaze_app_id")).value_str,
        app_key=(await get_config("backblaze_app_key")).value_str,
        bucket_name=(await get_config("backblaze_bucket_name")).value_str,
        base_path=(await get_config("backblaze_base_path")).value_str,
        base_url=(await get_config("backblaze_base_url")).value_str
    )
    return config
