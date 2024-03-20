from telegram import InlineKeyboardButton

from models import User
from registries import user_registry


class ConfigUser:
    """
    用户配置页面
    """
    text: str
    keyboard: list[list[InlineKeyboardButton]]

    def __init__(self, text, keyboard):
        self.text = text
        self.keyboard = keyboard


async def config_user(uid: int = None, page: int = 1, user: User = None) -> ConfigUser:
    """
    生成用户配置页面
    :param user: 可选, 用户对象， 与 UID 至少指定一个，同时指定时优先使用 user
    :param uid: 可选, 用户 ID, 与 user 至少指定一个，同时指定时优先使用 user
    :param page: 可选, 当前页码，默认首页
    :return: 用户配置页面
    """
    # 每页显示 5 个选项
    option_per_page = 5
    offset = (page - 1) * option_per_page
    # 当 user 和 uid 同时为空时抛出异常
    if user is None and uid is None:
        raise ValueError('uid 和 user 不能同时为空')
    # 当 user 为空时从数据库获取用户对象
    if user is None:
        user = await user_registry.get_user_by_id(uid)
    config: [(str, str)] = [
        ('昵称', user.nick_name),
        ('启用 AI 聊天', '是' if user.enable_chat else '否'),
        ('过滤等级', str(user.sanity_limit - 1)),
        ('允许 R18G', '是' if user.allow_r18g else '否')
    ]
    # config.append(('状态', user.status.value))
    keyboard: [[InlineKeyboardButton]] = [
        [InlineKeyboardButton('上一页', callback_data=f'conf:page:goto:{page - 1}')]
    ] if page > 1 else []
    all_keyboard = [
        [InlineKeyboardButton(f'修改昵称 (当前: {user.nick_name})', callback_data=f'conf:user:nick:edit')],
        [InlineKeyboardButton(
            '禁用 AI 聊天' if user.enable_chat else '启用 AI 聊天',
            callback_data=f'conf:user:chat:on' if not user.enable_chat else 'conf:user:chat:off')],
        [InlineKeyboardButton(f'修改过滤等级 (当前: {user.sanity_limit - 1})', callback_data='conf:user:san:edit')],
        [InlineKeyboardButton(
            '禁用 R18G' if user.allow_r18g else '启用 R18G',
            callback_data=f'conf:user:r18g:on' if not user.allow_r18g else 'conf:user:r18g:off')]
    ]
    keyboard += all_keyboard[offset:offset + option_per_page]
    if offset + option_per_page < len(all_keyboard):
        keyboard.append([InlineKeyboardButton('下一页', callback_data=f'conf:page:goto:{page + 1}')])
    text = f'用户配置 ({page}/{len(all_keyboard) // option_per_page + 1})\n\n'
    return ConfigUser(text, [keyboard])
