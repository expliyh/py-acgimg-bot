from telegram import InlineKeyboardButton

from registries import config_registry


class BotAdmin:
    """
    用户配置页面
    """
    text: str
    keyboard: list[list[InlineKeyboardButton]]

    def __init__(self, text, keyboard):
        self.text = text
        self.keyboard = keyboard


async def bot_admin(page: int = 1):
    option_per_page = 5
    offset = (page - 1) * option_per_page
    text = f'*机器人配置*\n\n'
    if page > 1:
        keyboard = [[InlineKeyboardButton('上一页', callback_data=f'conf:page:goto:{page - 1}')]]
    else:
        keyboard = []
    text += f'- Pixiv Token: {'已设置' if (await config_registry.get_pixiv_tokens()) is not None else '未设置'}\n\n'
    storage = await config_registry.get_config('storage_service_use')
    text += f'- Storage: {storage if storage is not None else '未设置'}\n\n'
    all_keyboard = [
        [InlineKeyboardButton('Pixiv Token', callback_data='conf:bot:pixiv:token:edit')],
        [InlineKeyboardButton('Storage', callback_data='conf:bot:storage:edit')],
    ]
    keyboard += all_keyboard[offset:offset + option_per_page]
    if offset + option_per_page < len(all_keyboard):
        keyboard.append([InlineKeyboardButton('下一页', callback_data=f'conf:page:goto:{page + 1}')])
    return BotAdmin(text, keyboard)
