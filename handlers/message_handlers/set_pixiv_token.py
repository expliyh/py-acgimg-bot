"""Message handler that stores Pixiv refresh tokens submitted via chat."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry, config_registry
from services import pixiv

from handlers.callback_handlers.conf_handlers.bot.panel import refresh_bot_config_panel
from handlers.registry import message_handler

logger = logging.getLogger(__name__)

_HANDLER_PREFIX = "set_pixiv_token"
_CANCEL_TOKEN = "-"


async def _delete_message_safely(bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to delete message %s in chat %s during Pixiv token setup",
            message_id,
            chat_id,
            exc_info=True,
        )

async def _reload_pixiv_state() -> None:
    await pixiv.read_token_from_config()
    if pixiv.enabled:
        await pixiv.token_refresh(force=True)


@message_handler
async def set_pixiv_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None or not message.text:
        return

    handler_key = await active_message_handler_registry.get(user.id)
    if not handler_key or not handler_key.startswith(_HANDLER_PREFIX):
        return

    parts = handler_key.split(":")
    if len(parts) < 4:
        logger.warning("Pixiv token handler metadata malformed for user %s: %s", user.id, handler_key)
        await active_message_handler_registry.delete(user_id=user.id)
        return

    mode = parts[1]
    panel_message_id_text = parts[2]
    token_id_text = parts[3]
    prompt_message_id_text = parts[4] if len(parts) >= 5 else None

    try:
        panel_message_id = int(panel_message_id_text)
    except ValueError:
        logger.warning("Invalid panel message id '%s' for user %s", panel_message_id_text, user.id)
        await active_message_handler_registry.delete(user_id=user.id)
        return

    token_id = 0
    if token_id_text and token_id_text != "0":
        try:
            token_id = int(token_id_text)
        except ValueError:
            logger.warning("Invalid token id '%s' for user %s", token_id_text, user.id)
            await active_message_handler_registry.delete(user_id=user.id)
            return

    prompt_message_id = None
    if prompt_message_id_text:
        try:
            prompt_message_id = int(prompt_message_id_text)
        except ValueError:
            logger.warning("Invalid prompt message id '%s' for user %s", prompt_message_id_text, user.id)

    submitted = message.text.strip()

    if submitted == _CANCEL_TOKEN:
        feedback = "已取消 Pixiv Token 操作"
    else:
        try:
            if mode == "add":
                await config_registry.add_pixiv_token(submitted, enabled=True)
                feedback = "已添加新的 Pixiv Refresh Token"
            elif mode == "update" and token_id > 0:
                await config_registry.update_pixiv_token(token_id, submitted)
                feedback = "已更新 Pixiv Refresh Token"
            else:
                feedback = "未识别的 Pixiv Token 操作"
                logger.warning("Unknown Pixiv token mode '%s' for user %s", mode, user.id)
            await _reload_pixiv_state()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to process Pixiv token submission for user %s", user.id)
            feedback = f"操作失败：{exc}"

    await active_message_handler_registry.delete(user_id=user.id)

    await refresh_bot_config_panel(
        context,
        chat_id=message.chat_id,
        message_id=panel_message_id,
    )

    await _delete_message_safely(context.bot, message.chat_id, prompt_message_id)
    await _delete_message_safely(context.bot, message.chat_id, message.message_id)

    await context.bot.send_message(chat_id=message.chat_id, text=feedback)
