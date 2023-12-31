import asyncio
import json
import logging
import random
import re

import telegram.error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import config
from pixiv import pixiv_api

import database as db_class
from database import *
import images

from .generate_inline_keyboard import *


async def get_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = context.args
    if cmd is None or cmd == "":
        return
    tmp = await pixiv_api.get_raw(int(cmd[0]))
    message = str(tmp)
    await context.bot.send_message(chat_id=config.developer_chat_id, text=message)
    return
