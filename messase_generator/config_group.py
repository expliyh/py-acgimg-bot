"""Generation helpers for the Telegram group configuration panel."""

from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton

from models import Group
from services import group_guard


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

    guard_settings = await group_guard.get_guard_settings(group.id)
    keyword_count = len(await group_guard.list_keyword_rules(group.id))

    lines = [
        "群组配置面板",
        "",
        f"群组 ID: {group.id}",
        f"名称: {group.name or '未设置'}",
        f"机器人启用: {_bool_icon(group.enable)}",
        f"允许涩图: {_bool_icon(group.allow_setu)}",
        f"允许 R18: {_bool_icon(allow_r18)}",
        "",
        "群管配置",
        f"进群验证: {_bool_icon(guard_settings.verification_enabled)}",
        f"验证超时: {guard_settings.verification_timeout} 秒",
        f"超时处理: {'踢出群组' if guard_settings.kick_on_timeout else '仅限制发言'}",
        f"关键字过滤: {_bool_icon(guard_settings.keyword_filter_enabled)}",
        f"关键字规则: {keyword_count} 条",
        "",
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
                "禁止涩图" if group.allow_setu else "允许涩图",
                callback_data=_build_callback(
                    group.id,
                    "setu:off" if group.allow_setu else "setu:on",
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
                "禁用进群验证" if guard_settings.verification_enabled else "启用进群验证",
                callback_data=_build_callback(
                    group.id,
                    "guard:verify:off" if guard_settings.verification_enabled else "guard:verify:on",
                    command_message_id,
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "超时改为仅限制" if guard_settings.kick_on_timeout else "超时改为踢出",
                callback_data=_build_callback(
                    group.id,
                    "guard:kick:off" if guard_settings.kick_on_timeout else "guard:kick:on",
                    command_message_id,
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "禁用关键字过滤" if guard_settings.keyword_filter_enabled else "启用关键字过滤",
                callback_data=_build_callback(
                    group.id,
                    "guard:filter:off" if guard_settings.keyword_filter_enabled else "guard:filter:on",
                    command_message_id,
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "设置验证提示",
                callback_data=_build_callback(group.id, "guard:message:set", command_message_id),
            )
        ],
        [
            InlineKeyboardButton(
                "验证超时 -30s",
                callback_data=_build_callback(group.id, "guard:timeout:dec", command_message_id),
            ),
            InlineKeyboardButton(
                "验证超时 +30s",
                callback_data=_build_callback(group.id, "guard:timeout:inc", command_message_id),
            ),
            InlineKeyboardButton(
                "自定义验证超时",
                callback_data=_build_callback(group.id, "guard:timeout:set", command_message_id),
            ),
        ],
        [
            InlineKeyboardButton(
                "查看关键字",
                callback_data=_build_callback(group.id, "guard:keywords:list", command_message_id),
            ),
            InlineKeyboardButton(
                "添加关键字",
                callback_data=_build_callback(group.id, "guard:keywords:add", command_message_id),
            ),
        ],
        [
            InlineKeyboardButton(
                "删除关键字",
                callback_data=_build_callback(group.id, "guard:keywords:remove", command_message_id),
            ),
            InlineKeyboardButton(
                "清空关键字",
                callback_data=_build_callback(group.id, "guard:keywords:clear", command_message_id),
            ),
        ],
        [
            InlineKeyboardButton(
                "AI 聊天 (暂未实现)",
                callback_data=_build_callback(group.id, "chat:todo", command_message_id),
            )
        ],
    ]

    return ConfigGroup(text=text, keyboard=keyboard)
