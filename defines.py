from enum import Enum


class ConfigKeys(Enum):
    BOT_TOKEN = "bot_token"
    BOT_NAME = "bot_name"
    OWNER_ID = "owner_id"
    BOT_URL = "bot_url"
    PIXIV_TOKENS = "pixiv_tokens"
    PIXIV_API_URL = "pixiv_api_url"
    OPENAI_API_URL = "openai_api_url"
    OPENAI_API_TOKENS = "openai_api_tokens"
    SANITY_LIMIT = "sanity_limit"
    ALLOW_R18G = "allow_r18g"
    ALLOW_GROUP_BY_DEFAULT = "allow_group_by_default"


class UserStatus(Enum):
    """
    用户状态
    """
    NORMAL = "Normal"
    INACTIVE = "Inactive"
    BLOCKED = "Blocked"


class GroupChatMode(Enum):
    """
    群组聊天记录的保存方法
    """
    # 每个群成员聊天记录独立
    SEPARATED = "Separated"
    # 所有群成员共享聊天记录
    MIXED = "Mixed"
