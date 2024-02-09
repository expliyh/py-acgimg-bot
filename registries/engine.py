from singleton_class_decorator import singleton
from sqlalchemy import select, update, create_engine, func, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncAttrs, async_sessionmaker, AsyncSession
from sqlalchemy.dialects.mysql import insert

from configs import config as config_file


def get_none_async_engine():
    url = (f"mariadb+mariadb://{config_file.db_username}:"
           f"{config_file.db_password}@{config_file.db_host}:{config_file.db_port}/"
           f"{config_file.db_name}?charset=utf8mb4")
    none_async_engine = create_engine(
        url,
        echo=True,
        echo_pool=True
    )
    return none_async_engine


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

    def new_session(self):
        async_session = async_sessionmaker(self.engine)
        return async_session

    def new_session_no_expire_on_commit(self):
        async_session = async_sessionmaker(self.engine, expire_on_commit=False)
        return async_session


engine = Engine()


def create_tables():
    non_async_engine = get_none_async_engine()
    from models import Base
    Base.metadata.create_all(non_async_engine)
