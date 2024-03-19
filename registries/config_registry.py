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


async def get_configs(key: str) -> list[Config]:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(Config).where(Config.key == key))
        configs: list[Config] = []
        for row in result.scalars():
            row: Config = row
            configs.append(row)
        return configs


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
