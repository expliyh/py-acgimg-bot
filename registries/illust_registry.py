import random

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Illustration

from .engine import engine


async def get_illust_info(pixiv_id: int) -> Illustration | None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(
            select(Illustration).where(Illustration.id == pixiv_id)
        )
        return result.scalars().first()


async def random_illust(sanity_limit: int = 5, r18g: bool = False):
    async with engine.new_session() as session:
        session: AsyncSession = session

        count_stmt = select(func.count(Illustration.id))
        if not r18g:
            count_stmt = count_stmt.where(Illustration.r18g.is_(False))
        count_stmt = count_stmt.where(Illustration.sanity_level <= sanity_limit)

        row_count = (await session.execute(count_stmt)).scalar_one()
        if row_count == 0:
            return None

        random_offset = random.randrange(row_count)

        stmt = select(Illustration)
        if not r18g:
            stmt = stmt.where(Illustration.r18g.is_(False))
        stmt = stmt.where(Illustration.sanity_level <= sanity_limit)
        stmt = stmt.offset(random_offset).limit(1)

        result = await session.execute(stmt)
        return result.scalars().first()
