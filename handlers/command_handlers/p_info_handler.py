from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from services import pixiv
from services.command_history import command_logger


@command_logger("pinfo")
async def p_info_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


p_info_handler = CommandHandler("pinfo", p_info_func)
