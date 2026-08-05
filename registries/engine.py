from pathlib import Path

from singleton_class_decorator import singleton
from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncAttrs, async_sessionmaker, AsyncSession, AsyncConnection

from configs import config as config_file
from models import Base


def _build_db_url() -> str:
    """Build the async SQLAlchemy URL for the configured database backend.

    Defaults to SQLite (``sqlite+aiosqlite``) so the application can start
    without any configuration. Set ``DATABASE_TYPE=mysql`` (or ``mariadb``)
    plus the ``DATABASE_*`` environment variables to use MariaDB/MySQL.
    """
    if config_file.db_type == 'sqlite':
        storage_dir = Path(__file__).resolve().parent.parent / "storage"
        storage_dir.mkdir(parents=True, exist_ok=True)
        db_path = storage_dir / "acgimg.db"
        return f"sqlite+aiosqlite:///{db_path.as_posix()}"
    return (
        f"mariadb+asyncmy://{config_file.db_username}:"
        f"{config_file.db_password}@{config_file.db_host}:{config_file.db_port}/"
        f"{config_file.db_name}?charset=utf8mb4"
    )


@singleton
class Engine:
    def __init__(self):
        self.engine = None

    def create(self):
        url = _build_db_url()
        if config_file.db_type == 'sqlite':
            self.engine = create_async_engine(
                url,
                echo=True,
                echo_pool=True,
            )
        else:
            self.engine = create_async_engine(
                url,
                echo=True,
                echo_pool=True,
                pool_recycle=3600
            )

    def new_session(self) -> AsyncSession:
        async_session = async_sessionmaker(self.engine, expire_on_commit=True)
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
