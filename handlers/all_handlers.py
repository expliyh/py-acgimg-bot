from telegram.ext import BaseHandler, CallbackQueryHandler, MessageHandler, filters

from .callback_handlers import callback_handler_func
from .command_handlers import all_command_handlers
from .message_handlers.group_guard import (
    handle_group_keyword_filter,
    handle_new_member_verification,
)
from .message_handlers.root import handle_incoming_message

# Group guard handlers to intercept new members and filter messages before logging.
new_member_verification_handler = MessageHandler(
    filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS,
    handle_new_member_verification,
    block=False,
)
keyword_filter_handler = MessageHandler(
    filters.ChatType.GROUPS & (filters.TEXT | filters.CAPTION),
    handle_group_keyword_filter,
    block=False,
)

# Log every message for persistence after more specific handlers had a chance to run.
message_logging_handler = MessageHandler(filters.ALL, handle_incoming_message, block=False)

all_handlers: list[BaseHandler] = [
    *all_command_handlers,
    CallbackQueryHandler(callback_handler_func),
    new_member_verification_handler,
    keyword_filter_handler,
    message_logging_handler,
]
