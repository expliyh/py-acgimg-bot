import logging

from fastapi import Request

from telegram import Update, Bot
from telegram.ext import Application, CallbackContext, CommandHandler

from configs import config
from registries import config_registry

logger = logging.getLogger(__name__)


async def start(update: Update, context) -> None:
    logger.info(f"Update START for user: {update.effective_user}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello!")


class TelegramBot:
    def __init__(self):
        self.tg_bot: Bot | None = None
        self.tg_app: Application | None = None

    async def config(self):
        tokens = await config_registry.get_bot_tokens()
        if len(tokens) > 1:
            raise Exception("Too many bot tokens, Multiple bot tokens are currently not supported")
        if len(tokens) == 0:
            raise Exception("No bot token found")
        token = tokens[0]
        self.tg_bot = Bot(token.token)
        await self.tg_bot.initialize()
        await self.tg_bot.set_webhook(f"https://{config.external_url}/tapi/")
        self.tg_app = Application.builder().token(token.token).build()
        self.tg_app.add_handler(CommandHandler("start", start))
        await self.tg_app.initialize()
        await self.tg_app.start()

    async def put_update(self, request: Request) -> None:
        update = Update.de_json(await request.json(), self.tg_bot)
        await self.tg_app.update_queue.put(update)


tg_bot = TelegramBot()
