from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from defines import UserStatus

from .engine import engine


async def add_user(user: User) -> None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        session.add(user)
        await session.commit()


async def get_user_by_id(user_id: int) -> User:
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar()
        if user is None:
            new_user = User(id=user_id)
            await add_user(new_user)
            return await get_user_by_id(user_id)
        return user


async def set_sanity_limit(user_id: int, sanity_limit: int) -> None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        await session.execute(update(User).where(User.id == user_id).values(sanity_limit=sanity_limit))
        await session.commit()


async def set_allow_r18g(user_id: int, allow_r18g: bool) -> None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        await session.execute(update(User).where(User.id == user_id).values(allow_r18g=allow_r18g))
        await session.commit()


async def set_status(user_id: int, status: UserStatus) -> None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        await session.execute(update(User).where(User.id == user_id).values(status=status))
        await session.commit()


async def set_enable_chat(user_id: int, enable_chat: bool) -> None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        await session.execute(update(User).where(User.id == user_id).values(enable_chat=enable_chat))
        await session.commit()


async def set_nick_name(user_id: int, nick_name: str | None) -> None:
    normalized = (nick_name or "").strip()
    value = normalized if normalized else None
    if value is not None and len(value) > 64:
        value = value[:64]

    async with engine.new_session() as session:
        session: AsyncSession = session
        await session.execute(update(User).where(User.id == user_id).values(nick_name=value))
        await session.commit()
