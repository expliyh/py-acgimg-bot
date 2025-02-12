import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from models import ActiveMessageHandler
from .engine import engine


async def delete(user_id: int, group_id: int = 0):
    async with engine.new_session() as session:
        session: AsyncSession = session
        # 删除操作，根据 user_id 和 group_id 条件
        await session.execute(
            sqlalchemy.delete(ActiveMessageHandler)
            .where(
                (ActiveMessageHandler.user_id == user_id) &
                (ActiveMessageHandler.group_id == group_id)
            )
        )
        await session.commit()


async def get(user_id: int, group_id: int = 0) -> str:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = (await session.execute(
            sqlalchemy.select(ActiveMessageHandler)
            .where(
                (ActiveMessageHandler.user_id == user_id) &
                (ActiveMessageHandler.group_id == group_id)
            )
        )).scalar_one_or_none()
        return result.handler_id if result else None

async def set(user_id: int, group_id: int = 0, handler_id: str = ""):
    async with engine.new_session() as session:
        session: AsyncSession = session
        # 检查是否已存在记录
        existing = (await session.execute(
            sqlalchemy.select(ActiveMessageHandler)
            .where(
                (ActiveMessageHandler.user_id == user_id) &
                (ActiveMessageHandler.group_id == group_id)
            )
        )).scalar_one_or_none()

        if existing:
            # 如果记录已存在，更新 handler_id
            existing.handler_id = handler_id
            await session.commit()
        else:
            # 如果记录不存在，插入新记录
            new_record = ActiveMessageHandler(
                user_id=user_id,
                group_id=group_id,
                handler_id=handler_id
            )
            session.add(new_record)
            await session.commit()
