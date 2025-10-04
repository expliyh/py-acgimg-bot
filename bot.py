import logging
from contextlib import suppress
from typing import Literal

from fastapi import Request

from telegram import Bot, Update, BotCommand
from telegram.ext import Application, CommandHandler, ApplicationBuilder

from configs import config
from handlers import all_handlers
from registries import config_registry

logger = logging.getLogger(__name__)

BOT_COMMAND_DEFINITIONS: list[tuple[str, str]] = [
    ("start", "\u5f00\u59cb\u4f7f\u7528\u673a\u5668\u4eba"),
    ("setu", "\u53d1\u9001\u968f\u673a\u6da9\u56fe"),
    ("option", "\u6253\u5f00\u4e2a\u4eba\u8bbe\u7f6e"),
    ("admin", "\u6253\u5f00\u7ba1\u7406\u9762\u677f"),
    ("pinfo", "\u67e5\u770b Pixiv \u63d2\u753b\u4fe1\u606f"),
]



async def start(update: Update, context) -> None:
    logger.info(f"Update START for user: {update.effective_user}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello!")


class TelegramBot:
    def __init__(self):
        self.tg_bot: Bot | None = None
        self.tg_app: Application | None = None
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

        self.tg_app = ApplicationBuilder().token(token_value).build()
        self.tg_app.add_handler(CommandHandler("start", start))
        self.tg_app.add_handlers(all_handlers)

        try:
            await self.tg_app.initialize()
        except Exception:
            logger.exception("Failed to initialize Telegram application")
            await self._shutdown()
            return

        self.tg_bot = self.tg_app.bot
        self._app_initialized = True

        await self._register_commands()

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

    async def shutdown(self) -> None:
        await self._shutdown()

    async def _shutdown(self) -> None:
        if self.tg_app:
            if self.tg_app.updater and self.tg_app.updater.running:
                with suppress(Exception):
                    await self.tg_app.updater.stop()
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

        if self.tg_app.updater and self.tg_app.updater.running:
            await self.tg_app.updater.stop()

        if not self.tg_app.running:
            await self.tg_app.start()

        if self.tg_app.update_queue is None:
            raise RuntimeError("Telegram application does not expose an update queue")

        webhook_url = self._build_webhook_url(external_url)
        await self.tg_bot.set_webhook(
            webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )

        self._mode = "webhook"
        logger.info("Telegram bot configured to use webhook mode: %s", webhook_url)

    async def _ensure_polling_mode(self) -> None:
        if not self.tg_bot or not self.tg_app:
            raise RuntimeError("Telegram bot is not initialized")

        if not self.tg_app.running:
            await self.tg_app.start()

        await self.tg_bot.delete_webhook(drop_pending_updates=True)

        if not self.tg_app.updater:
            raise RuntimeError("Telegram application updater is not available")

        if not self.tg_app.updater.running:
            await self.tg_app.updater.start_polling()

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

        payload = await request.json()
        update = Update.de_json(payload, self.tg_bot)

        queue = self.tg_app.update_queue
        if queue is None:
            raise RuntimeError("Telegram application does not expose an update queue")

        await queue.put(update)


tg_bot = TelegramBot()
