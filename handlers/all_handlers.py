from telegram.ext import BaseHandler, CallbackQueryHandler, MessageHandler, filters

from .callback_handlers import callback_handler_func
from .command_handlers import all_command_handlers
from .message_handlers.root import handle_incoming_message

# Log every message for persistence after more specific handlers had a chance to run.
message_logging_handler = MessageHandler(filters.ALL, handle_incoming_message, block=False)

all_handlers: list[BaseHandler] = [
    *all_command_handlers,
    CallbackQueryHandler(callback_handler_func),
    message_logging_handler,
]
