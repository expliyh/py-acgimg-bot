import asyncio
import logging
from typing import Literal

from fastapi import Request

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler

from configs import config
from handlers import all_handlers
from registries import config_registry

logger = logging.getLogger(__name__)


async def start(update: Update, context) -> None:
    logger.info(f"Update START for user: {update.effective_user}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello!")


class TelegramBot:
    def __init__(self):
        self.tg_bot: Bot | None = None
        self.tg_app: Application | None = None
        self.poll_task: asyncio.Task | None = None
        self._mode: Literal["webhook", "polling"] | None = None

    async def config(self):
        tokens = await config_registry.get_bot_tokens()
        if len(tokens) > 1:
            raise Exception("Too many bot tokens, Multiple bot tokens are currently not supported")
        if len(tokens) == 0:
            raise Exception("No bot token found")

        self._mode = None

        token = tokens[0]
        self.tg_bot = Bot(token.token)
        await self.tg_bot.initialize()

        self.tg_app = Application.builder().token(token.token).build()
        self.tg_app.add_handler(CommandHandler("start", start))
        self.tg_app.add_handlers(all_handlers)

        await self.tg_app.initialize()

        external_url = config.external_url.strip() if config.external_url else ""
        if external_url:
            await self._ensure_webhook_mode(external_url)
        else:
            logger.info("EXTERNAL_URL not provided; falling back to polling mode")
            await self._ensure_polling_mode()

    async def _ensure_webhook_mode(self, external_url: str) -> None:
        if not self.tg_bot or not self.tg_app:
            raise RuntimeError("Telegram bot is not initialized")

        if self.tg_app.running:
            await self.tg_app.stop()

        webhook_url = self._build_webhook_url(external_url)
        await self.tg_bot.set_webhook(webhook_url, drop_pending_updates=True)

        if not self.tg_app.running:
            await self.tg_app.start()

        self._mode = "webhook"
        logger.info("Telegram bot configured to use webhook mode: %s", webhook_url)

    async def _custom_polling(self, interval: float = 2.0):
        """
        自定义轮询：每隔 interval 秒调用 get_updates
        """
        offset = 0
        while True:
            print("POLL")
            try:
                updates = await self.tg_bot.get_updates(offset=offset, timeout=10)
                for update in updates:
                    offset = update.update_id + 1
                    # ✅ 关键：手动交给 PTB 处理
                    await self.tg_app.process_update(update)
            except Exception as e:
                print(f"Polling error: {e}")
            await asyncio.sleep(interval)

    async def _ensure_polling_mode(self) -> None:
        if not self.tg_bot or not self.tg_app:
            raise RuntimeError("Telegram bot is not initialized")

        if self.tg_app.running:
            # stop() will also stop updater if running
            await self.tg_app.stop()

        await self.tg_bot.delete_webhook(drop_pending_updates=True)

        self.poll_task = asyncio.create_task(self._custom_polling(interval=2.0))

        self._mode = "polling"
        logger.info("Telegram bot configured to use polling mode")

    @staticmethod
    def _build_webhook_url(base_url: str) -> str:
        normalized = base_url.strip()
        if not normalized:
            raise ValueError("EXTERNAL_URL is empty")
        if normalized.endswith("/"):
            normalized = normalized[:-1]
        if not normalized.startswith("http://") and not normalized.startswith("https://"):
            normalized = f"https://{normalized}"
        return f"{normalized}/tapi/"

    async def put_update(self, request: Request) -> None:
        if self._mode != "webhook":
            logger.debug("Received webhook update while not in webhook mode; ignoring")
            return

        if not self.tg_bot or not self.tg_app:
            raise RuntimeError("Telegram bot is not initialized")

        update = Update.de_json(await request.json(), self.tg_bot)
        await self.tg_app.process_update(update)


tg_bot = TelegramBot()
