from telegram import Update
from telegram.ext import ContextTypes

from handlers.callback_handlers.panel_utils import close_panel
from registries import active_message_handler_registry

from .chat_toggle import handle_chat_toggle
from .nick import handle_nick
from .panel import refresh_user_config_panel
from .sanity import handle_sanity
from .switch_r18g import switch_r18g


def _parse_command_message_id(cmd_parts: list[str]) -> int | None:
    if len(cmd_parts) <= 2:
        return None
    value = cmd_parts[2]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


handler_map = {
    "chat": handle_chat_toggle,
    "nick": handle_nick,
    "san": handle_sanity,
    "r18g": switch_r18g,
}


async def user_conf_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]):
    query = update.callback_query
    if query is None or not cmd:
        return

    section = cmd[0]

    if section == "panel" and len(cmd) > 1:
        action = cmd[1]
        command_message_id = _parse_command_message_id(cmd)
        if action == "refresh":
            await active_message_handler_registry.delete(user_id=update.effective_user.id)
            await refresh_user_config_panel(
                context,
                chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id,
                user_id=update.effective_user.id,
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
