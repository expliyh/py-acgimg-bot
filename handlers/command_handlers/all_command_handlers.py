from .admin_handler import admin_handler
from .option_handler import option_handler
from .setu_handler import setu_handler
from .p_info_handler import p_info_handler

all_command_handlers = [
    option_handler,
    setu_handler,
    p_info_handler,
    admin_handler
]
