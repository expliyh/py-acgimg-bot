import asyncio
import logging
import time
from contextlib import suppress
from datetime import timedelta
from typing import Awaitable, Callable, Literal

from fastapi import Request

from telegram import Bot, Update, BotCommand
from telegram.error import TelegramError, TimedOut
from telegram.ext import Application, CommandHandler, ApplicationBuilder, MessageHandler, ChatMemberHandler, ChatJoinRequestHandler, filters

from configs import config
from handlers import all_handlers
from registries import config_registry
from services.telegram_recovery import (
    PollActivity,
    StartupAbandoned,
    await_bounded,
    bootstrap_retry_count,
    build_api_request,
    build_updates_request,
    force_close_application,
    on_application_error,
    poll_stall_limit,
    polling_timeout,
    retry_telegram_call,
    shutdown_timeout,
    startup_attempt_timeout,
    watchdog_interval,
    healthcheck_failure_limit,
)

logger = logging.getLogger(__name__)

BOT_COMMAND_DEFINITIONS: list[tuple[str, str]] = [
    ("start", "\u5f00\u59cb\u4f7f\u7528\u673a\u5668\u4eba"),
    ("setu", "\u53d1\u9001\u968f\u673a\u6da9\u56fe"),
    ("push", "\u7ba1\u7406\u5458\u4e3b\u52a8\u63a8\u9001\u56fe\u7247"),
    ("option", "\u6253\u5f00\u4e2a\u4eba\u8bbe\u7f6e"),
    ("admin", "\u6253\u5f00\u7ba1\u7406\u9762\u677f"),
    ("pinfo", "\u67e5\u770b Pixiv \u63d2\u753b\u4fe1\u606f"),
    ("guard", "智能群管配置"),
    ("verify", "重新触发入群验证"),
    ("rules", "查看群规"),
    ("report", "回复消息举报"),
    ("notes", "查看群笔记"),
]



async def start(update: Update, context) -> None:
    logger.info(f"Update START for user: {update.effective_user}")
    chat = update.effective_chat
    if chat is None:
        logger.warning("START update has no chat; not sending a reply")
        return
    await retry_telegram_call(
        lambda: context.bot.send_message(chat_id=chat.id, text="Hello!"),
        "start reply",
    )


class TelegramBot:
    def __init__(self):
        self.tg_bot: Bot | None = None
        self.tg_app: Application | None = None
        self._mode: Literal["webhook", "polling"] | None = None
        self._app_initialized = False
        self._guard_worker = None
        self._image_push_worker = None
        self._lifecycle_lock = asyncio.Lock()
        self._poll_activity = PollActivity()
        self._health_failures = 0
        self._supervisor_task: asyncio.Task | None = None
        self._supervisor_stop = asyncio.Event()
        self._closing = False

    async def config(self):
        self._ensure_supervisor()
        async with self._lifecycle_lock:
            try:
                await self._configure()
            except BaseException:
                await self._shutdown()
                raise

    def _ensure_supervisor(self) -> None:
        if self._closing:
            return
        task = self._supervisor_task
        if task is not None and not task.done():
            return
        self._supervisor_stop = asyncio.Event()
        self._supervisor_task = asyncio.create_task(
            self._supervisor(),
            name="telegram-bot-supervisor",
        )
        logger.debug("Telegram recovery supervisor started")

    async def _supervisor(self) -> None:
        stop = self._supervisor_stop
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=watchdog_interval())
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                raise
            if stop.is_set() or self._closing:
                return
            await self._recovery_tick()

    async def _recovery_tick(self) -> None:
        if self._closing or self._lifecycle_lock.locked():
            return
        try:
            if not await self._needs_recovery():
                return
            logger.warning(
                "Telegram bot is unhealthy or not running; rebuilding the application"
            )
            await self.config()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram automatic recovery failed")

    async def _needs_recovery(self) -> bool:
        try:
            if await self._enabled_token() is None:
                return False
        except Exception:
            logger.exception("Could not read the Telegram bot token while checking health")
            return False
        app = self.tg_app
        if not self._app_initialized or app is None or self.tg_bot is None or self._mode is None:
            return True
        if not app.running:
            return True
        if self._mode == "polling":
            updater = app.updater
            if updater is None or not updater.running or self._poll_activity.stalled(poll_stall_limit()):
                return True
        if await self._probe_bot():
            self._health_failures = 0
            return False
        self._health_failures += 1
        limit = healthcheck_failure_limit()
        if self._health_failures < limit:
            logger.warning(
                "Telegram health check failed (%s/%s); not rebuilding yet",
                self._health_failures,
                limit,
            )
            return False
        return True

    async def _probe_bot(self) -> bool:
        bot = self.tg_bot
        if bot is None:
            return False
        try:
            await bot.get_me(
                connect_timeout=min(config.telegram_connect_timeout, 5.0),
                read_timeout=min(config.telegram_read_timeout, 10.0),
                write_timeout=min(config.telegram_write_timeout, 10.0),
                pool_timeout=config.telegram_pool_timeout,
            )
        except Exception as exc:
            logger.warning("Telegram health check failed: %s", exc)
            return False
        return True

    async def _enabled_token(self) -> str | None:
        tokens = await config_registry.get_bot_tokens()
        enabled = [
            token for token in tokens
            if token.enable and token.token and str(token.token).strip()
        ]
        if not enabled:
            return None
        return str(enabled[0].token).strip()

    async def _configure(self):
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
        self.tg_app = self._build_application(token_value)
        self._install_handlers(self.tg_app)

        try:
            if not await self._run_startup_step("initialize", self.tg_app.initialize):
                return
        except Exception:
            logger.exception("Failed to initialize Telegram application")
            await self._shutdown()
            return

        self.tg_bot = self.tg_app.bot
        self._app_initialized = True
        try:
            await self._start_workers()
        except Exception:
            logger.exception("Failed to start Telegram background workers")
            await self._shutdown()
            return

        await self._register_commands()
        await self._start_transport()

    def _build_application(self, token: str) -> Application:
        generation = self._poll_activity.generation
        return (
            ApplicationBuilder()
            .token(token)
            .request(build_api_request())
            .get_updates_request(
                build_updates_request(lambda url: self._poll_activity.note(generation, url))
            )
            .build()
        )

    @staticmethod
    def _install_handlers(app: Application) -> None:
        from services.moderation import runtime, verification
        app.add_handler(MessageHandler(filters.ChatType.GROUPS, runtime.preprocess), group=-10)
        app.add_handler(ChatMemberHandler(runtime.membership, ChatMemberHandler.ANY_CHAT_MEMBER), group=-10)
        app.add_handler(ChatJoinRequestHandler(verification.join_request), group=-10)
        app.add_handler(CommandHandler("start", start))
        app.add_handlers(all_handlers)
        app.add_handler(MessageHandler(filters.ChatType.GROUPS, runtime.operations), group=10)
        app.add_error_handler(on_application_error)

    async def _run_startup_step(
        self,
        label: str,
        factory: Callable[[], Awaitable],
    ) -> bool:
        """Run one startup phase with bounded attempts.

        Returns False when the application was torn down and the caller must stop.
        """

        timeout = startup_attempt_timeout()

        async def attempt():
            task = asyncio.create_task(factory())
            try:
                done, _pending = await asyncio.wait({task}, timeout=timeout)
            except asyncio.CancelledError:
                task.cancel()
                raise
            if task in done:
                return task.result()
            logger.error("Telegram %s exceeded %.1fs; cancelling the attempt", label, timeout)
            task.cancel()
            finished, _pending = await asyncio.wait({task}, timeout=1)
            if task not in finished:
                if self.tg_app is not None:
                    await force_close_application(self.tg_app)
                raise StartupAbandoned(
                    f"{label} did not stop after exceeding {timeout:.0f}s"
                )
            try:
                return task.result()
            except asyncio.CancelledError as exc:
                raise TimedOut(
                    f"{label} was cancelled after exceeding {timeout:.0f}s"
                ) from exc

        try:
            await retry_telegram_call(attempt, label)
        except StartupAbandoned:
            logger.error(
                "Telegram %s could not be cancelled; disabling it until automatic recovery",
                label,
            )
            await self._shutdown()
            return False
        return True

    async def _start_workers(self) -> None:
        from services.moderation.worker import Worker
        self._guard_worker = Worker(self.tg_bot)
        await self._guard_worker.start()
        from services.image_push import ImagePushWorker
        self._image_push_worker = ImagePushWorker(self.tg_bot)
        await self._image_push_worker.start()

    async def _start_transport(self) -> None:
        external_url = config.external_url.strip() if config.external_url else ""
        if external_url:
            try:
                if not await self._run_startup_step(
                    "webhook setup",
                    lambda: self._ensure_webhook_mode(external_url),
                ):
                    return
                return
            except Exception:
                logger.exception(
                    "Failed to configure webhook mode; falling back to polling mode"
                )

        try:
            if not await self._run_startup_step("polling setup", self._ensure_polling_mode):
                return
        except Exception:
            logger.exception(
                "Failed to configure Telegram bot in polling mode; disabling Telegram integration"
            )
            await self._shutdown()

    async def shutdown(self) -> None:
        self._closing = True
        try:
            await self._stop_supervisor()
            async with self._lifecycle_lock:
                await self._shutdown()
        finally:
            self._closing = False

    async def _stop_supervisor(self) -> None:
        self._supervisor_stop.set()
        task = self._supervisor_task
        self._supervisor_task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _shutdown(self) -> None:
        self._poll_activity.bump()
        try:
            await self._stop_workers()
            app = self.tg_app
            initialized = self._app_initialized
            self.tg_app = None
            self.tg_bot = None
            self._mode = None
            self._app_initialized = False
            self._health_failures = 0
            if app is not None:
                await self._stop_application(app, initialized)
        except Exception:
            logger.exception("Error while shutting down the Telegram application")
            self.tg_app = None
            self.tg_bot = None
            self._mode = None
            self._app_initialized = False

    async def _stop_workers(self) -> None:
        await self._stop_worker(self._guard_worker, "moderation")
        await self._stop_worker(self._image_push_worker, "image push")
        self._guard_worker = None
        self._image_push_worker = None

    async def _stop_worker(self, worker, label: str) -> None:
        if worker is None:
            return
        try:
            finished = await await_bounded(
                worker.stop(),
                shutdown_timeout(),
                label=f"Telegram {label} worker shutdown",
            )
        except Exception:
            logger.exception("Telegram %s worker shutdown failed", label)
            finished = False
        if finished:
            return
        runner = getattr(worker, "runner", None)
        if isinstance(runner, asyncio.Task) and not runner.done():
            runner.cancel()
        children = getattr(worker, "children", ())
        if isinstance(children, (set, list, tuple)):
            for child in list(children):
                if isinstance(child, asyncio.Task) and not child.done():
                    child.cancel()

    async def _stop_application(self, app: Application, initialized: bool) -> None:
        async def graceful() -> None:
            if app.updater and app.updater.running:
                with suppress(Exception):
                    await app.updater.stop()
            if app.running:
                await app.stop()
            if initialized:
                with suppress(RuntimeError):
                    await app.shutdown()
            else:
                # Application.shutdown() returns immediately until initialize()
                # succeeds, which would leave the HTTP clients open after a
                # failed getMe.
                bot = getattr(app, "bot", None)
                shutdown_bot = getattr(bot, "shutdown", None)
                if shutdown_bot is not None:
                    with suppress(Exception):
                        await shutdown_bot()

        try:
            finished = await await_bounded(
                graceful(),
                shutdown_timeout(),
                label="Telegram application shutdown",
            )
        except Exception:
            logger.exception("Telegram application shutdown failed")
            finished = False
        if not finished:
            logger.error(
                "Telegram shutdown exceeded %.1fs; forcing HTTP clients and polling tasks closed",
                shutdown_timeout(),
            )
            await force_close_application(app)

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
        if not config.telegram_webhook_secret:
            raise ValueError("Webhook mode requires TELEGRAM_WEBHOOK_SECRET")
        await self.tg_bot.set_webhook(
            webhook_url,
            # Keep updates received while the service was offline. In
            # particular, my_chat_member is the only signal that lets us
            # discover a group the bot was added to without a new message.
            drop_pending_updates=False,
            allowed_updates=Update.ALL_TYPES,
            secret_token=config.telegram_webhook_secret,
        )

        self._mode = "webhook"
        logger.info("Telegram bot configured to use webhook mode: %s", webhook_url)

    async def _ensure_polling_mode(self) -> None:
        if not self.tg_bot or not self.tg_app:
            raise RuntimeError("Telegram bot is not initialized")

        if not self.tg_app.running:
            await self.tg_app.start()

        # Do not discard updates collected while the process was stopped.
        # The polling updater will deliver them immediately after startup.
        await self.tg_bot.delete_webhook(drop_pending_updates=False)

        if not self.tg_app.updater:
            raise RuntimeError("Telegram application updater is not available")

        if not self.tg_app.updater.running:
            await self.tg_app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=False,
                timeout=timedelta(seconds=polling_timeout()),
                bootstrap_retries=bootstrap_retry_count(),
                error_callback=self._on_polling_error,
            )

        self._mode = "polling"
        # The first long poll has not returned yet. Starting the stall clock here
        # avoids treating a healthy boot as a stalled poller.
        self._poll_activity.last_success_at = time.monotonic()
        logger.info("Telegram bot configured to use polling mode")

    def _on_polling_error(self, error: TelegramError) -> None:
        logger.error(
            "Telegram polling error (%s): %s. The polling loop will keep retrying.",
            type(error).__name__,
            error,
            exc_info=error,
        )

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
