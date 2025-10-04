from .root import root
from .all_message_handlers import all_message_handlers

index = {
    "root": root,
    **all_message_handlers,
}
