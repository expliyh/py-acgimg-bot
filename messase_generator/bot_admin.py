"""Generation helpers for the Telegram bot admin configuration panel."""

from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton
from telegram.helpers import escape_markdown

from registries import config_registry


@dataclass(slots=True)
class BotAdmin:
    text: str
    keyboard: list[list[InlineKeyboardButton]]


def _bool_icon(value: bool) -> str:
    return "✅" if value else "❌"


def _is_truthy(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return False


def _storage_label(current: str | None) -> str:
    mapping = {
        "local": "本地存储",
        "backblaze": "Backblaze B2",
        "webdav": "WebDAV",
        "disabled": "已禁用",
        "none": "未设置",
    }
    if not current:
        return "未设置"
    return mapping.get(current.lower(), current)




def _build_callback(base: str, command_message_id: int | None) -> str:
    if command_message_id is None:
        return base
    return f"{base}:{command_message_id}"
def _backblaze_ready(config) -> bool:
    return bool(config.app_id and config.app_key and config.bucket_name)


def _webdav_ready(config) -> bool:
    return bool(config.endpoint and config.username and config.password)


def _local_ready(config) -> bool:
    return bool(config.root_path)


def _md(line: str) -> str:
    return escape_markdown(line, version=2)


async def bot_admin(page: int = 1, *, command_message_id: int | None = None) -> BotAdmin:
    allow_r18g = _is_truthy(await config_registry.get_config("allow_r18g"))
    enable_on_new_group = _is_truthy(await config_registry.get_config("enable_on_new_group"))

    storage_choice = await config_registry.get_config("storage_service_use")
    if isinstance(storage_choice, str):
        storage_choice = storage_choice.strip().lower() or None

    backblaze_config = await config_registry.get_backblaze_config()
    webdav_config = await config_registry.get_webdav_config()
    local_config = await config_registry.get_local_storage_config()

    pixiv_tokens = await config_registry.get_pixiv_tokens()
    pixiv_configured = any(token.token for token in pixiv_tokens)
    pixiv_enabled = any(token.enable for token in pixiv_tokens)

    cache_config = await config_registry.get_telegram_cache_config()
    cache_backend_label = "内存" if cache_config.backend == "memory" else "Redis"
    cache_redis = cache_config.redis_url or "未配置"

    lines = [
        "机器人配置面板",
        "",
        "功能开关:",
        f"- 允许 R18G: {_bool_icon(allow_r18g)}",
        f"- 新群自动启用: {_bool_icon(enable_on_new_group)}",
        "",
        "存储服务:",
        f"- 当前驱动: {_storage_label(storage_choice)}",
        f"  · 本地存储: {'已配置' if _local_ready(local_config) else '未配置'}",
        f"  · Backblaze B2: {'已配置' if _backblaze_ready(backblaze_config) else '未配置'}",
        f"  · WebDAV: {'已配置' if _webdav_ready(webdav_config) else '未配置'}",
        "",
        "Pixiv Tokens:",
        f"- 配置数量: {len(pixiv_tokens)}",
        f"- 已启用: {pixiv_enabled and '是' or '否'}",
        f"- 可用: {pixiv_configured and '是' or '否'}",
        "",
        "Telegram 缓存:",
        f"- 后端: {cache_backend_label}",
        f"- TTL: {cache_config.ttl_seconds} 秒",
        f"- Redis 地址: {cache_redis}",
    ]

    text = "\n".join(_md(line) for line in lines)

    keyboard: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                f"切换允许 R18G ({'开启' if allow_r18g else '关闭'})",
                callback_data="conf:bot:feature:allow_r18g:toggle",
            )
        ],
        [
            InlineKeyboardButton(
                f"切换新群自动启用 ({'开启' if enable_on_new_group else '关闭'})",
                callback_data="conf:bot:feature:enable_on_new_group:toggle",
            )
        ],
        [
            InlineKeyboardButton(
                f"设置存储服务 ({_storage_label(storage_choice)})",
                callback_data="conf:bot:storage:menu",
            )
        ],
        [
            InlineKeyboardButton(
                "配置 Pixiv API",
                callback_data="conf:bot:pixiv:menu",
            )
        ],
        [
            InlineKeyboardButton(
                "缓存设置",
                callback_data="conf:bot:cache:menu",
            )
        ],
        [
            InlineKeyboardButton("刷新", callback_data=_build_callback("conf:bot:panel:refresh", command_message_id)),
            InlineKeyboardButton("关闭", callback_data=_build_callback("conf:bot:panel:close", command_message_id)),
        ],
    ]

    return BotAdmin(text=text, keyboard=keyboard)
