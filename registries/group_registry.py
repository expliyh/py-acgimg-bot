import random

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Illustration, Group
from defines import GroupStatus

from .engine import engine


async def add_group(group: Group) -> None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        session.add(group)
        await session.commit()


async def get_group_by_id(group_id: int) -> Group:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(GroupStatus).where(Group.id == group_id))
        group = result.scalar()
        if result is None:
            new_group = Group(id=group_id)
            await add_group(new_group)
            return await get_group_by_id(group_id)
        return group
