import unicodedata
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
    field_validator,
    model_validator,
)

VERIFICATION_MESSAGE_MAX_LENGTH = 2000
ACTION_REASON_MAX_LENGTH = 1000


def validate_record_name(value: str, label: str = "名称") -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label}不能为空")
    if len(value) > 100:
        raise ValueError(f"{label}过长")
    if "/" in value:
        raise ValueError(f"{label}不能包含斜杠")
    if value in {".", ".."}:
        raise ValueError(f"{label}必须是安全的路径片段")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Policy(StrictModel):
    verification_enabled: bool = False
    verification_timeout: int = Field(60, ge=15, le=3600)
    verification_message: str | None = Field(
        None, max_length=VERIFICATION_MESSAGE_MAX_LENGTH
    )
    kick_on_timeout: bool = True
    keyword_filter_enabled: bool = False
    verification_mode: Literal["button", "math"] = "button"
    join_auto_approve: bool = False
    join_requests_enabled: bool = False
    rules_enabled: bool = False
    flood_enabled: bool = False
    flood_window: int = Field(10, ge=1, le=300)
    flood_limit: int = Field(6, ge=2, le=100)
    repeat_window: int = Field(30, ge=1, le=600)
    repeat_limit: int = Field(3, ge=2, le=50)
    raid_enabled: bool = False
    raid_window: int = Field(60, ge=10, le=600)
    raid_limit: int = Field(10, ge=2, le=1000)
    raid_duration: int = Field(600, ge=60, le=86400)
    warning_limit: int = Field(3, ge=1, le=100)
    warning_days: int = Field(7, ge=1, le=365)
    mute_seconds: int = Field(3600, ge=60, le=31536000)
    log_days: int = Field(90, ge=7, le=3650)
    domain_allowlist: list[str] = Field(default_factory=list, max_length=200)
    welcome_enabled: bool = False
    welcome_text: str = Field("欢迎 {user} 加入 {chat}！", max_length=2000)
    goodbye_enabled: bool = False
    goodbye_text: str = Field("{user} 离开了 {chat}", max_length=2000)
    rules_text: str = Field("", max_length=4000)
    replies_enabled: bool = False
    clean_service_messages: bool = False
    ai_spam: bool = False
    ai_abuse: bool = False
    ai_images: bool = False
    ai_auto_threshold: float = Field(0.95, ge=0.7, le=1)
    ai_review_threshold: float = Field(0.7, ge=0, le=1)
    ai_daily_limit: int = Field(500, ge=1, le=100000)
    timezone: str = "Asia/Shanghai"

    @field_validator("verification_message")
    @classmethod
    def verification_prompt(cls, value):
        if value is None:
            return None
        return value.strip() or None

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError("无效时区") from exc
        return value

    @field_validator("domain_allowlist")
    @classmethod
    def domains(cls, values):
        result = []
        for value in values:
            host = value.strip().lower().rstrip(".")
            if not host or any(x in host for x in ("/", ":", "*", " ", "@")):
                raise ValueError("白名单应填写域名，不含协议、路径或通配符")
            result.append(host.encode("idna").decode("ascii"))
        return sorted(set(result))

    @model_validator(mode="after")
    def thresholds(self):
        if self.ai_review_threshold > self.ai_auto_threshold:
            raise ValueError("复核阈值不能超过自动处罚阈值")
        return self


PolicyPatch = create_model(
    "PolicyPatch",
    __base__=StrictModel,
    **{
        name: (field.annotation | None, None)
        for name, field in Policy.model_fields.items()
    },
)


class Rule(StrictModel):
    kind: Literal["keyword", "regex", "link", "invite", "forward", "media"]
    pattern: str = Field("", max_length=512)
    case_sensitive: bool = False
    action: Literal["delete", "delete_warn"] = "delete_warn"
    enabled: bool = True

    @model_validator(mode="after")
    def valid_pattern(self):
        stripped = self.pattern.strip()
        if self.kind in {"keyword", "regex", "media"} and not stripped:
            raise ValueError("规则内容不能为空")
        if self.kind == "keyword" and not any(
            unicodedata.category(c) != "Cf" and not c.isspace()
            for c in unicodedata.normalize("NFKC", self.pattern)
        ):
            raise ValueError("规则内容不能为空")
        if self.kind == "regex":
            import regex

            try:
                regex.compile(self.pattern)
            except regex.error as exc:
                raise ValueError("无效正则表达式") from exc
        if self.kind == "media" and self.pattern not in {
            "photo",
            "video",
            "audio",
            "voice",
            "document",
            "sticker",
            "animation",
            "poll",
            "video_note",
            "album",
        }:
            raise ValueError("不支持的媒体类型")
        return self


class ActionRequest(StrictModel):
    action: Literal[
        "warn",
        "unwarn",
        "mute",
        "unmute",
        "kick",
        "ban",
        "unban",
        "delete",
        "pin",
        "unpin",
        "purge",
    ]
    user_id: int | None = Field(None, gt=0)
    message_id: int | None = Field(None, gt=0)
    end_message_id: int | None = Field(None, gt=0)
    duration: int = Field(3600, ge=60, le=31536000)
    reason: str = Field("管理员操作", max_length=ACTION_REASON_MAX_LENGTH)
    event_id: str | None = None
    request_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def target(self):
        if self.action in {"delete", "pin", "unpin", "purge"}:
            if not self.message_id:
                raise ValueError("需要消息 ID")
        elif not self.user_id:
            raise ValueError("需要成员 ID")
        if self.action == "purge" and (
            not self.end_message_id
            or not 0 <= self.end_message_id - self.message_id < 100
        ):
            raise ValueError("每次清理必须为连续 1–100 条消息")
        return self


class OperationResult(StrictModel):
    id: str
    action: str
    status: str
    reason: str
    data: dict = Field(default_factory=dict)


class Content(StrictModel):
    kind: Literal["reply", "note", "announcement"]
    name: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4000)
    enabled: bool = True
    due_at: datetime | None = None
    repeat: Literal["once", "daily", "weekly"] = "once"
    timezone: str = "Asia/Shanghai"

    @field_validator("name")
    @classmethod
    def normalized_name(cls, value):
        return validate_record_name(value, "内容名称")

    @field_validator("text")
    @classmethod
    def normalized_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("内容正文不能为空")
        return value

    @model_validator(mode="after")
    def schedule(self):
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError) as exc:
            raise ValueError("无效时区") from exc
        if self.kind == "announcement" and (
            self.due_at is None or self.due_at.tzinfo is None
        ):
            raise ValueError("公告需要包含时区的执行时间")
        return self


class AIConfig(StrictModel):
    base_url: str = ""
    api_key: str | None = Field(None, max_length=2000)
    text_model: str = Field("", max_length=200)
    vision_model: str = Field("", max_length=200)
    timeout: int = Field(20, ge=5, le=120)
    concurrency: int = Field(2, ge=1, le=10)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        value = value.rstrip("/")
        if value:
            url = urlparse(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("需要不含凭据的 HTTP(S) API 地址")
        return value


class AIVerdict(StrictModel):
    category: Literal["safe", "spam", "abuse", "image"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=1000)
    evidence: str = Field("", max_length=1000)
    sanity_level: Literal[5, 6] | None = None
    r18g: bool | None = None


class ReviewDecision(StrictModel):
    decision: Literal["dismiss", "punish", "revoke", "approve_join", "reject_join"]
    reason: str = Field("管理员复核", max_length=1000)
