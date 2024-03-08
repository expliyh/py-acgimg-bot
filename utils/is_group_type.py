from telegram import Chat


def is_group_type(input_type: str):
    if input_type in (Chat.GROUP, Chat.SUPERGROUP):
        return True
    return False
