import logging

from telegram import Update
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import ContextTypes

from services.permissions import has_super_user_access
from services import pixiv
from services.command_history import command_logger
from services.pixiv_service import PixivWorkNotFound
from messase_generator.illustration import ILLUSTRATION_PARSE_MODE
from handlers.registry import bot_handler

logger = logging.getLogger(__name__)

_SEND_FAILED = "插画信息发送失败，请稍后再试。"
_FETCH_FAILED = "获取插画信息失败，请稍后再试。"
_NOT_FOUND = "未找到该 Pixiv 作品，请检查 ID 是否正确。"
_INVALID_ID = "请提供有效的 Pixiv 作品 ID，例如 /pinfo 12345678。"


async def _reply(message, text: str, **extra) -> None:
    if message is None:
        return
    await message.reply_text(
        text=text,
        reply_to_message_id=message.message_id,
        **extra,
    )


async def _reply_send_failed(message, pixiv_id: int) -> None:
    try:
        await _reply(message, _SEND_FAILED)
    except TelegramError:
        logger.exception("Failed to send /pinfo error reply for %s", pixiv_id)
        raise


@bot_handler
@command_logger("pinfo")
async def p_info_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if not await has_super_user_access(user_id):
        await _reply(message, "您没有权限使用此命令。")
        return
    if not pixiv.enabled:
        await _reply(message, "Pixiv 功能未启用，请联系管理员配置令牌。")
        return
    if not context.args:
        await _reply(message, "用法：/pinfo <Pixiv 作品 ID>")
        return

    raw_id = context.args[0].strip()
    if not raw_id.isdigit() or int(raw_id) <= 0:
        await _reply(message, _INVALID_ID)
        return
    pixiv_id = int(raw_id)

    try:
        illust = await pixiv.get_illust_info_by_pixiv_id(pixiv_id)
    except PixivWorkNotFound:
        logger.info("Pixiv work %s was not found", pixiv_id)
        await _reply(message, _NOT_FOUND)
        return
    except Exception:
        logger.exception("Failed to fetch Pixiv illustration %s", pixiv_id)
        await _reply(message, _FETCH_FAILED)
        return

    try:
        text = illust.get_markdown()
    except Exception:
        logger.exception("Failed to render /pinfo illustration %s", pixiv_id)
        await _reply_send_failed(message, pixiv_id)
        return

    try:
        await _reply(message, text, parse_mode=ILLUSTRATION_PARSE_MODE)
    except BadRequest as exc:
        # The formatted message was rejected, so nothing was delivered.
        logger.warning("Telegram rejected /pinfo text for %s: %s", pixiv_id, exc)
        await _reply_send_failed(message, pixiv_id)
    except NetworkError:
        # Timeouts and transport errors may already have delivered the message.
        logger.exception("Network error while sending /pinfo for %s", pixiv_id)
        raise
    except TelegramError:
        logger.exception("Failed to send /pinfo illustration %s", pixiv_id)
        await _reply_send_failed(message, pixiv_id)
    return
