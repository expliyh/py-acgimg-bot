"""Aggregate all bot handlers registered via decorators."""

from handlers.registry import iter_bot_handlers

# Import modules for side effects so their handlers register before aggregation.
from . import add_pixiv_handler, admin_handler, option_handler, p_info_handler, setu_handler


all_command_handlers = iter_bot_handlers()
