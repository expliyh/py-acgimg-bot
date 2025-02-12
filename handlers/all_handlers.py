from telegram.ext import BaseHandler, CallbackQueryHandler

from .callback_handlers import callback_handler_func
from .command_handlers import all_command_handlers

all_handlers: [BaseHandler] = []
all_handlers.extend(all_command_handlers)
all_handlers.append(CallbackQueryHandler(callback_handler_func))
