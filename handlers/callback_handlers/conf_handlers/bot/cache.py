"""Callback handlers for Telegram cache configuration."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry, config_registry
from services.telegram_cache import telegram_cache_manager

from .panel import refresh_bot_config_panel


def _build_menu(config: config_registry.TelegramCacheConfig) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    rows.append(
        [
            InlineKeyboardButton(
                f"使用内存缓存{' ✅' if config.backend == 'memory' else ''}",
                callback_data="conf:bot:cache:set_backend:memory",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                f"使用 Redis 缓存{' ✅' if config.backend == 'redis' else ''}",
                callback_data="conf:bot:cache:set_backend:redis",
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                f"设置缓存 TTL (当前: {config.ttl_seconds}s)",
                callback_data="conf:bot:cache:set_ttl",
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                "配置 Redis 地址" if not config.redis_url else "更新 Redis 地址",
                callback_data="conf:bot:cache:set_redis",
            )
        ]
    )

    if config.redis_url:
        rows.append(
            [
                InlineKeyboardButton(
                    "清除 Redis 地址",
                    callback_data="conf:bot:cache:clear_redis",
                )
            ]
        )

    rows.append([InlineKeyboardButton("返回", callback_data="conf:bot:panel:refresh")])

    return InlineKeyboardMarkup(rows)


async def handle_cache(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]) -> None:
    query = update.callback_query
    if query is None or not cmd:
        return

    action = cmd[0]
    config = await config_registry.get_telegram_cache_config()

    if action == "menu":
        markup = _build_menu(config)
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            reply_markup=markup,
        )
        await query.answer("已打开缓存设置")
        return

    if action == "set_backend" and len(cmd) >= 2:
        backend = cmd[1]
        if backend not in {"memory", "redis"}:
            await query.answer("不支持的缓存后端", show_alert=True)
            return
        await config_registry.set_telegram_cache_backend(backend)
        await telegram_cache_manager.reset()
        await query.answer(f"已切换缓存后端为 {backend}")
        await refresh_bot_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
        )
        return

    if action == "set_ttl":
        await active_message_handler_registry.set(
            user_id=update.effective_user.id,
            handler_id=f"set_cache_ttl:{update.effective_message.message_id}",
        )
        await query.answer("请输入新的缓存 TTL（秒）")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="请发送新的缓存 TTL（单位: 秒，最小 30）",
        )
        return

    if action == "set_redis":
        await active_message_handler_registry.set(
            user_id=update.effective_user.id,
            handler_id=f"set_cache_redis:{update.effective_message.message_id}",
        )
        await query.answer("请输入 Redis 地址")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "请发送 Redis 连接地址，例如 redis://:password@host:6379/0。\n"
                "若需清除，请发送单个减号 -。"
            ),
        )
        return

    if action == "clear_redis":
        await config_registry.set_telegram_cache_redis_url(None)
        await telegram_cache_manager.reset()
        await query.answer("已清除 Redis 配置")
        await refresh_bot_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
        )
        return

    await query.answer()
