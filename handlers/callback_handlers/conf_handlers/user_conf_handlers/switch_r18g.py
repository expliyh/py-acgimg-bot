import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from registries import user_registry
import messase_generator


async def update_panel(update, context):
    msg = await messase_generator.config_user(1, await user_registry.get_user_by_id(update.effective_user.id))
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        text=msg.text
    )
    await context.bot.edit_message_reply_markup(
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        reply_markup=InlineKeyboardMarkup(msg.keyboard)
    )


async def disable_r18g(update: telegram.Update, context):
    await user_registry.set_allow_r18g(update.effective_user.id, False)
    await update_panel(update, context)
    return


async def enable_r18g(update: telegram.Update, context):
    await user_registry.set_allow_r18g(update.effective_user.id, True)
    await update_panel(update, context)
    return


async def warn_r18g(update: telegram.Update, context):
    # 编辑消息文本
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        text="警告：此内容可能包含不适合所有受众的敏感内容。请确认您已满18岁。"
    )

    # 创建内联键盘按钮
    keyboard = [
        [InlineKeyboardButton("确认", callback_data='conf:user:r18g:confirm')],  # 使用红色圆圈模拟红色按钮
        [InlineKeyboardButton("取消", callback_data='conf:user:r18g:cancel')]  # 取消按钮
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 编辑消息的回复标记
    await context.bot.edit_message_reply_markup(
        chat_id=update.effective_chat.id,
        message_id=update.effective_message.message_id,
        reply_markup=reply_markup
    )


async def switch_r18g(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE, cmd: list[str]):
    match cmd[0]:
        case 'off':
            await disable_r18g(update, context)
        case 'confirm':
            await enable_r18g(update, context)
        case 'on':
            await warn_r18g(update, context)
        case 'cancel':
            await update_panel(update, context)

    pass
