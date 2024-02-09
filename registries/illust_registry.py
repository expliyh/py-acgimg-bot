import random

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Illustration
from defines import UserStatus

from .engine import engine


async def get_illust_info(pixiv_id: int) -> Illustration | None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(Illustration).where(Illustration.id == pixiv_id))
        return result.scalar().first()


async def random_illust(sanity_limit: int = 5, r18g: bool = False):
    async with engine.new_session() as session:
        session: AsyncSession = session
        row_count: int | None = (await session.execute(select(func.count(Illustration.id)))).scalars().first()
        if row_count is None or row_count == 0:
            return None
        random_offset = random.randint(0, row_count - 1)
        stmt = select(Illustration)
        if not r18g:
            stmt = stmt.where(Illustration.r18g == False)
        stmt = stmt.where(Illustration.sanity_level <= sanity_limit)
        stmt = stmt.offset(random_offset).limit(1)
        result = await session.execute(stmt)
        return result.scalar().first()
