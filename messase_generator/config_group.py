"""Generation helpers for the Telegram group configuration panel."""

from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton

from models import Group


@dataclass(slots=True)
class ConfigGroup:
    """Container for the rendered group configuration panel."""

    text: str
    keyboard: list[list[InlineKeyboardButton]]


def _bool_icon(value: bool) -> str:
    return "✅" if value else "❌"


def _build_callback(group_id: int, suffix: str, command_message_id: int | None) -> str:
    base = f"conf:group:{group_id}:{suffix}"
    if command_message_id is None:
        return base
    return f"{base}:{command_message_id}"


async def config_group(*, group: Group | None = None, command_message_id: int | None = None) -> ConfigGroup:
    """Compose the inline configuration panel for the given group."""

    if group is None:
        raise ValueError("group 不能为空")

    allow_r18 = group.sanity_limit >= 7

    lines = [
        "群组配置面板",
        "",
        f"群组 ID: {group.id}",
        f"名称: {group.name or '未设置'}",
        f"机器人启用: {_bool_icon(group.enable)}",
        f"允许 R18: {_bool_icon(allow_r18)}",
        "AI 聊天: 🚧 暂未实现",
    ]

    text = "\n".join(lines)

    keyboard: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                "刷新",
                callback_data=_build_callback(group.id, "panel:refresh", command_message_id),
            ),
            InlineKeyboardButton(
                "关闭",
                callback_data=_build_callback(group.id, "panel:close", command_message_id),
            ),
        ],
        [
            InlineKeyboardButton(
                "禁用机器人" if group.enable else "启用机器人",
                callback_data=_build_callback(
                    group.id,
                    "enable:off" if group.enable else "enable:on",
                    command_message_id,
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "禁止 R18" if allow_r18 else "允许 R18",
                callback_data=_build_callback(
                    group.id,
                    "r18:off" if allow_r18 else "r18:on",
                    command_message_id,
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "AI 聊天 (暂未实现)",
                callback_data=_build_callback(group.id, "chat:todo", command_message_id),
            )
        ],
    ]

    return ConfigGroup(text=text, keyboard=keyboard)
