from telegram.ext import BaseHandler

from .command_handlers import all_command_handlers

all_handlers: [BaseHandler] = []
all_handlers.extend(all_command_handlers)
