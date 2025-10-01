import asyncio
import logging
from contextlib import suppress
from typing import Literal

from fastapi import Request

from telegram import Bot, Update, BotCommand
from telegram.ext import Application, CommandHandler

from configs import config
from handlers import all_handlers
from registries import config_registry

logger = logging.getLogger(__name__)

BOT_COMMAND_DEFINITIONS: list[tuple[str, str]] = [
    ("start", "开始使用机器人"),
    ("setu", "发送随机涩图"),
    ("option", "打开个人设置"),
    ("admin", "打开管理面板"),
    ("pinfo", "查看 Pixiv 插画信息"),
]


async def start(update: Update, context) -> None:
    logger.info(f"Update START for user: {update.effective_user}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello!")


class TelegramBot:
    def __init__(self):
        self.tg_bot: Bot | None = None
        self.tg_app: Application | None = None
        self.poll_task: asyncio.Task | None = None
        self._mode: Literal["webhook", "polling"] | None = None
        self._app_initialized = False

    async def config(self):
        tokens = await config_registry.get_bot_tokens()
        enabled_tokens = [
            token for token in tokens if token.enable and token.token and token.token.strip()
        ]

        if not enabled_tokens:
            logger.warning(
                "No enabled Telegram bot token found; Telegram integration is disabled"
            )
            await self._shutdown()
            return

        if len(enabled_tokens) > 1:
            logger.warning(
                "Multiple enabled Telegram bot tokens detected; using the first enabled token"
            )

        token_value = enabled_tokens[0].token.strip()

        await self._shutdown()

        self.tg_bot = Bot(token_value)
        try:
            await self.tg_bot.initialize()
        except Exception:
            logger.exception("Failed to initialize Telegram bot with provided token")
            await self._shutdown()
            return

        self.tg_app = Application.builder().token(token_value).build()
        self.tg_app.add_handler(CommandHandler("start", start))
        self.tg_app.add_handlers(all_handlers)

        try:
            await self.tg_app.initialize()
        except Exception:
            logger.exception("Failed to initialize Telegram application")
            await self._shutdown()
            return

        await self._register_commands()

        self._app_initialized = True

        external_url = config.external_url.strip() if config.external_url else ""
        if external_url:
            try:
                await self._ensure_webhook_mode(external_url)
                return
            except Exception:
                logger.exception(
                    "Failed to configure webhook mode; falling back to polling mode"
                )

        try:
            await self._ensure_polling_mode()
        except Exception:
            logger.exception(
                "Failed to configure Telegram bot in polling mode; disabling Telegram integration"
            )
            await self._shutdown()

    async def _shutdown(self) -> None:
        if self.poll_task:
            self.poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.poll_task
            self.poll_task = None

        if self.tg_app:
            if self.tg_app.running:
                await self.tg_app.stop()
            if self._app_initialized:
                with suppress(RuntimeError):
                    await self.tg_app.shutdown()
            self.tg_app = None

        self.tg_bot = None
        self._mode = None
        self._app_initialized = False

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
        """Custom polling: fetch updates every `interval` seconds."""
        offset = 0
        while True:
            print("POLL")
            try:
                updates = await self.tg_bot.get_updates(offset=offset, timeout=10)
                for update in updates:
                    offset = update.update_id + 1
                    # Hand updates over to PTB manually
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

    def _build_supported_commands(self) -> list[BotCommand]:
        return [BotCommand(name, description) for name, description in BOT_COMMAND_DEFINITIONS]

    async def _register_commands(self) -> None:
        if not self.tg_bot:
            logger.warning("Cannot register commands without an initialized bot instance")
            return

        desired_commands = self._build_supported_commands()
        try:
            existing_commands = await self.tg_bot.get_my_commands()
        except Exception:
            logger.exception("Failed to fetch existing bot commands; forcing command refresh")
            existing_commands = []

        if existing_commands == desired_commands:
            return

        try:
            await self.tg_bot.delete_my_commands()
        except Exception:
            logger.exception("Failed to clear existing bot commands before update")

        try:
            await self.tg_bot.set_my_commands(desired_commands)
        except Exception:
            logger.exception("Failed to register bot commands on Telegram")
        else:
            logger.info("Registered %d bot command(s)", len(desired_commands))

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
