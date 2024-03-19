from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Config
from .engine import engine


class BotToken:
    token: str
    enable: bool

    def __init__(self, token: str, enable: bool):
        self.token = token
        self.enable = enable


async def get_bot_tokens() -> list[BotToken]:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(Config).where(Config.key == "bot_token"))
        tokens: list[BotToken] = []
        for i in result.scalars():
            tokens.append(BotToken(i.value_str, i.value_bool))
        return tokens
