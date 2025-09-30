"""Generation helpers for the Telegram user configuration panel."""

from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton

from defines import UserStatus
from models import User


@dataclass(slots=True)
class ConfigUser:
    """Container for the rendered user configuration panel."""

    text: str
    keyboard: list[list[InlineKeyboardButton]]


_STATUS_LABELS = {
    UserStatus.NORMAL: "正常",
    UserStatus.INACTIVE: "待启用",
    UserStatus.BLOCKED: "已封禁",
}


def _bool_icon(value: bool) -> str:
    return "✅" if value else "❌"


def _display_status(status: UserStatus | None) -> str:
    if status is None:
        return "未知"
    return _STATUS_LABELS.get(status, status.value)


def _shorten(text: str, limit: int = 20) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


async def config_user(page: int = 1, user: User | None = None) -> ConfigUser:
    """Compose the inline configuration panel for the given user."""

    if user is None:
        raise ValueError("user 不能为空")

    nick = user.nick_name.strip() if user.nick_name else "未设置"
    display_nick = _shorten(nick)
    sanity_level = max(user.sanity_limit - 1, 0)

    lines = [
        "用户配置面板",
        "",
        f"用户 ID: {user.id}",
        f"状态: {_display_status(user.status)}",
        f"昵称: {nick}",
        f"AI 聊天: {_bool_icon(user.enable_chat)}",
        f"过滤等级: L{sanity_level}",
        f"允许 R18G: {_bool_icon(user.allow_r18g)}",
    ]

    text = "\n".join(lines)

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("刷新", callback_data="conf:user:panel:refresh")],
        [InlineKeyboardButton(f"修改昵称 (当前: {display_nick})", callback_data="conf:user:nick:edit")],
        [
            InlineKeyboardButton(
                ("禁用 AI 聊天" if user.enable_chat else "启用 AI 聊天"),
                callback_data="conf:user:chat:off" if user.enable_chat else "conf:user:chat:on",
            )
        ],
        [InlineKeyboardButton(f"调整过滤等级 (L{sanity_level})", callback_data="conf:user:san:edit")],
        [
            InlineKeyboardButton(
                "禁用 R18G" if user.allow_r18g else "启用 R18G",
                callback_data="conf:user:r18g:off" if user.allow_r18g else "conf:user:r18g:on",
            )
        ],
    ]

    return ConfigUser(text=text, keyboard=keyboard)
