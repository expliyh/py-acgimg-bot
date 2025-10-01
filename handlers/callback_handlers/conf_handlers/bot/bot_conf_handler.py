from telegram import Update
from telegram.ext import ContextTypes

from .feature_flags import handle_feature_flag
from .panel import refresh_bot_config_panel
from .storage import handle_storage
from .pixiv import handle_pixiv
from .cache import handle_cache

handler_map = {
    "feature": handle_feature_flag,
    "storage": handle_storage,
    "pixiv": handle_pixiv,
    "cache": handle_cache,
}


async def bot_conf_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]):
    query = update.callback_query
    if query is None or not cmd:
        return

    section = cmd[0]

    if section == "panel" and len(cmd) > 1 and cmd[1] == "refresh":
        await refresh_bot_config_panel(
            context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
        )
        await query.answer("已刷新")
        return

    handler = handler_map.get(section)
    if handler is None:
        await query.answer()
        return

    await handler(update, context, cmd[1:])
