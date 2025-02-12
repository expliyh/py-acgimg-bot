from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Config
from .engine import engine


class Token:
    token: str
    enable: bool

    def __init__(self, token: str, enable: bool):
        """
        初始化 Token 对象。
        :param token: 用于验证的 API 令牌
        :param enable: 令牌是否启用（布尔值）
        """
        self.token = token
        self.enable = enable


class BackBlazeConfig:
    app_id: str | None
    app_key: str | None
    bucket_name: str | None
    base_path: str | None
    base_url: str | None

    def set_app_id(self, app_id: str):
        """
        设置 B2 应用 ID。
        """
        self.app_id = app_id

    def set_app_key(self, app_key: str):
        """
        设置 B2 应用密钥。
        """
        self.app_key = app_key

    def set_bucket_name(self, bucket_name: str):
        """
        设置存储桶名称。
        """
        self.bucket_name = bucket_name

    def set_base_path(self, base_path: str):
        """
        设置基础存储路径。
        如果存在，确保路径以斜杠开头和结尾。
        """
        if base_path is None:
            self.base_path = None
            return
        self.base_path = base_path
        if not self.base_path.endswith("/"):
            self.base_path += "/"
        while self.base_path.startswith("/"):
            self.base_path = self.base_path[1:]

    def set_base_url(self, base_url: str):
        """
        设置基础 URL。
        如果存在，确保 URL 不以斜杠结尾。
        """
        if base_url is None:
            self.base_url = None
            return
        self.base_url = base_url
        while self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]

    def __init__(
            self,
            app_id: str = None,
            app_key: str = None,
            bucket_name: str = None,
            base_path: str = None,
            base_url: str = None
    ):
        """
        初始化 BackBlaze 配置。
        """
        self.app_id = app_id
        self.app_key = app_key
        self.bucket_name = bucket_name
        self.set_base_path(base_path)
        self.set_base_url(base_url)


async def add_config(config: Config, default: str | bool) -> None:
    """
    将配置添加到数据库中。
    如果配置已存在，则更新其值。
    """
    # 如果 value_str 或 value_bool 为 None，则使用默认值
    if config.value_str is None:
        config.value_str = default if isinstance(default, str) else ""
    if config.value_bool is None:
        config.value_bool = default if isinstance(default, bool) else False

    async with engine.new_session() as session:
        session: AsyncSession = session
        # 合并操作，如果记录存在则更新，否则插入
        await session.merge(config)
        await session.commit()


async def get_configs(key: str) -> list[Config]:
    """
    根据 key 获取多个配置项。
    """
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(Config).where(Config.key == key))
        return list(result.scalars())


async def get_config_detail(key: str) -> Config | None:
    """
    根据 key 获取单个配置项的详细信息（Config 对象）。
    """
    async with engine.new_session() as session:
        session: AsyncSession = session
        result = await session.execute(select(Config).where(Config.key == key))
        return result.scalar_one_or_none()


async def get_config(key: str) -> str | bool | None:
    """
    根据 key 获取配置项的值，自动返回 str 或 bool 类型。
    """
    config = await get_config_detail(key)
    if config is None:
        return None
    # 如果 value_str 不为 None，则返回字符串类型
    if config.value_str is not None:
        return config.value_str
    # 否则返回布尔类型
    elif config.value_bool is not None:
        return config.value_bool
    else:
        return None


async def get_bot_tokens() -> list[Token]:
    """
    获取所有机器人的 API 令牌。
    """
    configs = await get_configs("bot_token")
    return [Token(i.value_str, i.value_bool) for i in configs]


async def get_pixiv_tokens() -> list[Token]:
    """
    获取所有 Pixiv 的 API 令牌。
    """
    configs = await get_configs("pixiv_token")
    return [Token(i.value_str, i.value_bool) for i in configs]


async def get_backblaze_config() -> BackBlazeConfig:
    """
    获取 Backblaze 的完整配置。
    """
    return BackBlazeConfig(
        app_id=await get_config("backblaze_app_id"),
        app_key=await get_config("backblaze_app_key"),
        bucket_name=await get_config("backblaze_bucket_name"),
        base_path=await get_config("backblaze_base_path"),
        base_url=await get_config("backblaze_base_url")
    )