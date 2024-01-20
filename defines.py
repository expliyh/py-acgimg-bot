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


class MessageType(Enum):
    """
    消息类型
    """
    TEXT = "Text"
    MARKDOWN = "Markdown"
    PHOTO = "Photo"
    VIDEO = "Video"
    ANIMATION = "Animation"
    AUDIO = "Audio"
    VOICE = "Voice"
    DOCUMENT = "Document"
    STICKER = "Sticker"
    CONTACT = "Contact"
    LOCATION = "Location"
    VENUE = "Venue"
    VIDEO_NOTE = "VideoNote"
    INVOICE = "Invoice"
    SUCCESSFUL_PAYMENT = "SuccessfulPayment"
    GAME = "Game"
    POLL = "Poll"
    DICE = "Dice"
    NEW_CHAT_MEMBERS = "NewChatMembers"
    LEFT_CHAT_MEMBER = "LeftChatMember"
    NEW_CHAT_TITLE = "NewChatTitle"
    NEW_CHAT_PHOTO = "NewChatPhoto"
    DELETE_CHAT_PHOTO = "DeleteChatPhoto"
    GROUP_CHAT_CREATED = "GroupChatCreated"
    SUPERGROUP_CHAT_CREATED = "SupergroupChatCreated"
    CHANNEL_CHAT_CREATED = "ChannelChatCreated"
    MIGRATE_TO_CHAT_ID = "MigrateToChatId"
    MIGRATE_FROM_CHAT_ID = "MigrateFromChatId"
    PINNED_MESSAGE = "PinnedMessage"
    INVOICE_PAID = "InvoicePaid"
    CONNECTED_WEBSITE = "ConnectedWebsite"
    PASSPORT_DATA = "PassportData"
    PROXIMITY_ALERT_TRIGGERED = "ProximityAlertTriggered"
    VOICE_CHAT_SCHEDULED = "VoiceChatScheduled"
    VOICE_CHAT_STARTED = "VoiceChatStarted"
    VOICE_CHAT_ENDED = "VoiceChatEnded"
    VOICE_CHAT_PARTICIPANTS_INVITED = "VoiceChatParticipantsInvited"
    MESSAGE_AUTO_DELETE_TIMER_CHANGED = "MessageAutoDeleteTimerChanged"
    UNKNOWN = "Unknown"


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
