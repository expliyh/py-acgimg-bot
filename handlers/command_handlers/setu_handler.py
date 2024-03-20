from telegram import Update
from telegram.ext import CommandHandler

from defines import UserStatus, GroupStatus
from exps import UserBlockedError, GroupBlockedError

from utils import is_group_type

from registries import user_registry, group_registry


async def setu(update: Update, context) -> None:
    user = await user_registry.get_user_by_id(update.effective_user.id)
    if user.status == UserStatus.BLOCKED:
        raise UserBlockedError("您已被禁止使用本Bot")
    if user.status == UserStatus.INACTIVE:
        raise UserBlockedError("您未启用本Bot, 请先到设置中启用。")
    chat_id = update.effective_chat.id
    is_group = is_group_type(update.effective_chat.type)
    if is_group:
        group = await group_registry.get_group_by_id(chat_id)
        if group.status == GroupStatus.BLOCKED:
            raise GroupBlockedError("本群组已被禁止使用本Bot")


setu_handler = CommandHandler("setu", setu)
