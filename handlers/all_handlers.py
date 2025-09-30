from telegram.ext import BaseHandler, CallbackQueryHandler, MessageHandler, filters

from .callback_handlers import callback_handler_func
from .command_handlers import all_command_handlers
from .message_handlers.root import handle_incoming_message

all_handlers: [BaseHandler] = []
all_handlers.append(MessageHandler(filters.ALL, handle_incoming_message, block=False))
all_handlers.extend(all_command_handlers)
all_handlers.append(CallbackQueryHandler(callback_handler_func))
