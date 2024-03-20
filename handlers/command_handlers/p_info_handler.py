from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from services import pixiv


async def p_info_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pixiv_id = context.args[0]
    illust = await pixiv.get_illust_info_by_pixiv_id(pixiv_id)
    await update.message.reply_markdown(
        text=illust.get_markdown(),
        reply_to_message_id=update.message.message_id
    )
    return


p_info_handler = CommandHandler("pinfo", p_info_func)
