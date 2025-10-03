from telegram import Update
from telegram.ext import ContextTypes

from services.permissions import has_super_user_access
from services import pixiv
from services.command_history import command_logger
from handlers.registry import bot_handler


@bot_handler
@command_logger("pinfo")
async def p_info_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else None
    if not await has_super_user_access(user_id):
        await update.message.reply_text(
            text="您没有权限使用此命令。",
            reply_to_message_id=update.message.message_id,
        )
        return
    if not pixiv.enabled:
        await update.message.reply_text(
            text="Pixiv 功能未启用，请联系管理员配置令牌。",
            reply_to_message_id=update.message.message_id,
        )
        return
    pixiv_id = context.args[0]
    illust = await pixiv.get_illust_info_by_pixiv_id(pixiv_id)
    await update.message.reply_markdown(
        text=illust.get_markdown(),
        reply_to_message_id=update.message.message_id
    )
    return

