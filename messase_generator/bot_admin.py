from telegram import InlineKeyboardButton
from telegram.helpers import escape_markdown

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


# 配置按钮的数据结构
CONFIG_BUTTONS = [
    {'text': 'Pixiv Token', 'callback_data': 'conf:bot:pixiv:token:edit'},
    {'text': 'Storage', 'callback_data': 'conf:bot:storage:edit'},
    {'text': 'API Key', 'callback_data': 'conf:bot:api_key:edit'},
    {'text': 'Log Level', 'callback_data': 'conf:bot:log_level:edit'},
    {'text': 'Notification', 'callback_data': 'conf:bot:notification:edit'},
]


async def bot_admin(page: int = 1):
    # 每页显示的选项数量
    option_per_page = 5

    # 计算偏移量
    offset = (page - 1) * option_per_page

    # 初始化文本和键盘
    text = '*机器人配置*\n\n'
    keyboard = []

    # 添加上一页按钮（如果当前不是第一页）
    if page > 1:
        keyboard.append([InlineKeyboardButton('上一页', callback_data=f'conf:page:goto:{page - 1}')])

    # 添加当前页的配置按钮
    current_page_buttons = CONFIG_BUTTONS[offset:offset + option_per_page]
    for button in current_page_buttons:
        keyboard.append([InlineKeyboardButton(button['text'], callback_data=button['callback_data'])])

    # 添加下一页按钮（如果还有更多按钮）
    if offset + option_per_page < len(CONFIG_BUTTONS):
        keyboard.append([InlineKeyboardButton('下一页', callback_data=f'conf:page:goto:{page + 1}')])

    # 获取并显示配置状态
    pixiv_token_status = '已设置' if (await config_registry.get_pixiv_tokens()) is not None else '未设置'
    storage_status = await config_registry.get_config('storage_service_use') or '未设置'

    text += escape_markdown(f'- Pixiv Token: {pixiv_token_status}\n\n', version=2)
    text += escape_markdown(f'- Storage: {storage_status}\n\n', version=2)

    return BotAdmin(text, keyboard)
