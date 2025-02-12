# 定义消息处理函数
from telegram import Update
from telegram.ext import ContextTypes


def root(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_message = update.message.text.lower()
