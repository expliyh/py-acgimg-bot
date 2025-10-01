from telegram import Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.panel_utils import close_panel

from .cache import handle_cache
from .feature_flags import handle_feature_flag
from .panel import refresh_bot_config_panel
from .pixiv import handle_pixiv
from .storage import handle_storage


def _parse_command_message_id(cmd_parts: list[str]) -> int | None:
    if len(cmd_parts) <= 2:
        return None
    raw_value = cmd_parts[2]
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


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

    if section == "panel" and len(cmd) > 1:
        action = cmd[1]
        command_message_id = _parse_command_message_id(cmd)
        if action == "refresh":
            await refresh_bot_config_panel(
                context,
                chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id,
                command_message_id=command_message_id,
            )
            await query.answer("已刷新")
            return
        if action == "close":
            await close_panel(
                update,
                context,
                user_id=update.effective_user.id,
                command_message_id=command_message_id,
            )
            return

    handler = handler_map.get(section)
    if handler is None:
        await query.answer()
        return

    await handler(update, context, cmd[1:])
