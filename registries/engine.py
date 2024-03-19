from singleton_class_decorator import singleton
from sqlalchemy import select, update, create_engine, func, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncAttrs, async_sessionmaker, AsyncSession, AsyncConnection
from sqlalchemy.dialects.mysql import insert

from configs import config as config_file
from models import Base


@singleton
class Engine:
    def __init__(self):
        self.engine = None

    def create(self):
        url = (f"mariadb+asyncmy://{config_file.db_username}:"
               f"{config_file.db_password}@{config_file.db_host}:{config_file.db_port}/"
               f"{config_file.db_name}?charset=utf8mb4")
        self.engine = create_async_engine(
            url,
            echo=True,
            echo_pool=True,
            pool_recycle=3600
        )

    def new_session(self) -> AsyncSession:
        async_session = async_sessionmaker(self.engine)
        return async_session()

    async def create_all(self):
        if self.engine is None:
            self.create()
        async with self.engine.begin() as conn:
            conn: AsyncConnection = conn
            await conn.run_sync(Base.metadata.create_all)

    def new_session_no_expire_on_commit(self):
        async_session = async_sessionmaker(self.engine, expire_on_commit=False)
        return async_session


engine = Engine()
