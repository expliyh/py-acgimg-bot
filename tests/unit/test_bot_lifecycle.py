"""Telegram application lifecycle without opening a network connection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import TelegramError

from registries.config_registry import Token
from tests.unit.telegram_fakes import Bag, make_context, make_update


class FakeUpdater:
    def __init__(self):
        self.running = False
        self.stop = AsyncMock()
        self.start_polling = AsyncMock(side_effect=self._mark_running)

    def _mark_running(self, **kwargs):
        self.running = True


class FakeApp:
    def __init__(self):
        self.bot = Bag(
            get_me=AsyncMock(),
            set_webhook=AsyncMock(),
            delete_webhook=AsyncMock(),
            get_my_commands=AsyncMock(return_value=[]),
            delete_my_commands=AsyncMock(),
            set_my_commands=AsyncMock(),
            shutdown=AsyncMock(),
        )
        self.updater = FakeUpdater()
        self.running = False
        self.update_queue = asyncio.Queue()
        self.initialize = AsyncMock()
        self.stop = AsyncMock()
        self.shutdown = AsyncMock()
        self.add_handler = Mock()
        self.add_handlers = Mock()
        self.add_error_handler = Mock()

    async def start(self):
        self.running = True


def _builder(app):
    builder = Mock()
    builder.token.return_value = builder
    builder.request.return_value = builder
    builder.get_updates_request.return_value = builder
    builder.build.return_value = app
    return Mock(return_value=builder)


@pytest.fixture
def bot_module(monkeypatch):
    import bot as module

    async def once(factory, label):
        return await factory()

    monkeypatch.setattr(module, "retry_telegram_call", once)
    monkeypatch.setattr(module, "startup_attempt_timeout", lambda: 0.05)
    monkeypatch.setattr(module, "shutdown_timeout", lambda: 0.05)
    monkeypatch.setattr(module, "watchdog_interval", lambda: 0.01)
    monkeypatch.setattr(module, "force_close_application", AsyncMock())
    monkeypatch.setattr(module, "poll_stall_limit", lambda: 10**9)
    monkeypatch.setattr(module, "build_api_request", Mock())
    monkeypatch.setattr(module, "build_updates_request", Mock(return_value=Mock()))
    return module


def _new_bot(module):
    return module.TelegramBot()


async def test_start_reply_and_missing_chat(bot_module):
    context = make_context()
    await bot_module.start(make_update(), context)
    context.bot.send_message.assert_awaited()
    update = make_update()
    update.effective_chat = None
    await bot_module.start(update, context)


async def test_configure_success_failure_and_webhook_fallback(bot_module, monkeypatch):
    module = bot_module
    app = FakeApp()
    monkeypatch.setattr(module, "ApplicationBuilder", _builder(app))
    tokens = [
        Token(token=" first ", enable=True, id=1),
        Token(token=" second ", enable=True, id=2),
        Token(token="   ", enable=True, id=3),
        Token(token="off", enable=False, id=4),
    ]
    monkeypatch.setattr(module.config_registry, "get_bot_tokens", AsyncMock(return_value=tokens))
    bot = _new_bot(module)
    bot._start_workers = AsyncMock()
    monkeypatch.setattr(module.config, "external_url", "", raising=False)
    await bot.config()
    assert bot._mode == "polling"
    assert bot._app_initialized is True

    bot._run_startup_step = AsyncMock(return_value=False)
    await bot._configure()
    bot._run_startup_step = AsyncMock(side_effect=RuntimeError("init"))
    await bot._configure()
    assert bot.tg_app is None

    real_step = module.TelegramBot._run_startup_step
    bot._run_startup_step = real_step.__get__(bot, module.TelegramBot)
    monkeypatch.setattr(module.config, "external_url", "https://example.com", raising=False)
    monkeypatch.setattr(module.config, "telegram_webhook_secret", "", raising=False)

    async def fail_webhook(factory, label):
        if label == "webhook setup":
            raise RuntimeError("webhook")
        return await factory()

    monkeypatch.setattr(module, "retry_telegram_call", fail_webhook)
    app2 = FakeApp()
    monkeypatch.setattr(module, "ApplicationBuilder", _builder(app2))
    await bot._configure()
    assert bot._mode == "polling"

    monkeypatch.setattr(module.config_registry, "get_bot_tokens", AsyncMock(return_value=[]))
    await bot._configure()
    assert bot.tg_app is None
    await bot.shutdown()


async def test_startup_step_timeout_and_abandoned(bot_module, monkeypatch):
    module = bot_module
    bot = _new_bot(module)
    app = FakeApp()
    bot.tg_app = app

    async def quick():
        return "ok"

    assert await bot._run_startup_step("initialize", quick) is True

    async def hang():
        await asyncio.sleep(30)

    monkeypatch.setattr(module, "retry_telegram_call", lambda factory, label: factory())
    with pytest.raises(module.TimedOut):
        await bot._run_startup_step("initialize", hang)

    started = asyncio.Event()

    async def stubborn():
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(30)

    async def run_factory(factory, label):
        return await factory()

    monkeypatch.setattr(module, "retry_telegram_call", run_factory)
    monkeypatch.setattr(module, "startup_attempt_timeout", lambda: 0.01)
    task = asyncio.create_task(bot._run_startup_step("initialize", stubborn))
    await started.wait()
    assert await task is False


async def test_workers_transport_and_shutdown(bot_module, monkeypatch):
    module = bot_module
    bot = _new_bot(module)
    app = FakeApp()
    bot.tg_app = app
    bot.tg_bot = app.bot
    bot._app_initialized = True

    class Worker:
        def __init__(self, tg_bot):
            self.runner = asyncio.create_task(asyncio.sleep(30))
            self.children = {asyncio.create_task(asyncio.sleep(30))}

        async def start(self):
            return None

        async def stop(self):
            return None

    monkeypatch.setattr("services.moderation.worker.Worker", Worker)
    monkeypatch.setattr("services.image_push.ImagePushWorker", Worker)
    await bot._start_workers()
    async def skip_awaitable(awaitable, *args, **kwargs):
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        return False

    monkeypatch.setattr(module, "await_bounded", skip_awaitable)
    await bot._stop_workers()
    await asyncio.sleep(0)
    assert bot._guard_worker is None
    await bot._stop_worker(None, "moderation")

    monkeypatch.setattr(module.config, "external_url", "https://example.com/", raising=False)
    monkeypatch.setattr(module.config, "telegram_webhook_secret", "secret", raising=False)
    await bot._ensure_webhook_mode("https://example.com")
    assert bot._mode == "webhook"
    app.running = True
    app.updater.running = True
    await bot._ensure_webhook_mode("example.com")
    with pytest.raises(RuntimeError):
        await module.TelegramBot()._ensure_webhook_mode("https://example.com")
    app.update_queue = None
    with pytest.raises(RuntimeError):
        await bot._ensure_webhook_mode("https://example.com")
    with pytest.raises(ValueError):
        module.TelegramBot._build_webhook_url("  ")
    assert module.TelegramBot._build_webhook_url("example.com/") == "https://example.com/tapi/"

    app.update_queue = asyncio.Queue()
    app.updater = FakeUpdater()
    await bot._ensure_polling_mode()
    assert bot._mode == "polling"
    app.updater = None
    with pytest.raises(RuntimeError):
        await bot._ensure_polling_mode()
    with pytest.raises(RuntimeError):
        bare = module.TelegramBot()
        await bare._ensure_polling_mode()

    bot._on_polling_error(TelegramError("poll"))
    commands = bot._build_supported_commands()
    app.bot.get_my_commands = AsyncMock(return_value=commands)
    await bot._register_commands()
    app.bot.get_my_commands = AsyncMock(side_effect=RuntimeError("get"))
    app.bot.delete_my_commands = AsyncMock(side_effect=RuntimeError("del"))
    app.bot.set_my_commands = AsyncMock(side_effect=RuntimeError("set"))
    await bot._register_commands()
    bot.tg_bot = None
    await bot._register_commands()

    app.running = True
    app.updater = FakeUpdater()
    app.updater.running = True
    bot.tg_app = app
    bot._app_initialized = True
    monkeypatch.setattr(module, "await_bounded", AsyncMock(return_value=False))
    await bot._stop_application(app, True)
    module.force_close_application.assert_awaited()
    async def explode(awaitable, *args, **kwargs):
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        raise RuntimeError("stop")

    monkeypatch.setattr(module, "await_bounded", explode)
    await bot._stop_application(app, False)

    monkeypatch.setattr(bot, "_stop_workers", AsyncMock(side_effect=RuntimeError("shut")))
    await bot._shutdown()


async def test_recovery_supervisor_and_webhook_update(bot_module, monkeypatch):
    module = bot_module
    bot = _new_bot(module)
    monkeypatch.setattr(module.config_registry, "get_bot_tokens", AsyncMock(return_value=[Token(token="abc", enable=True, id=1)]))
    assert await bot._enabled_token() == "abc"
    monkeypatch.setattr(module.config_registry, "get_bot_tokens", AsyncMock(return_value=[Token(token="  ", enable=True, id=1)]))
    assert await bot._enabled_token() is None

    app = FakeApp()
    app.running = True
    app.updater.running = True
    bot.tg_app = app
    bot.tg_bot = app.bot
    bot._app_initialized = True
    bot._mode = "polling"
    bot._poll_activity.last_success_at = module.time.monotonic()
    monkeypatch.setattr(module, "poll_stall_limit", lambda: 10**9)
    monkeypatch.setattr(bot, "_probe_bot", AsyncMock(return_value=True))
    monkeypatch.setattr(module.config_registry, "get_bot_tokens", AsyncMock(return_value=[Token(token="abc", enable=True, id=1)]))
    assert await bot._needs_recovery() is False
    monkeypatch.setattr(bot, "_probe_bot", AsyncMock(return_value=False))
    monkeypatch.setattr(module, "healthcheck_failure_limit", lambda: 2)
    assert await bot._needs_recovery() is False
    assert await bot._needs_recovery() is True
    bot.tg_app = None
    assert await bot._needs_recovery() is True
    monkeypatch.setattr(bot, "_enabled_token", AsyncMock(side_effect=RuntimeError("db")))
    assert await bot._needs_recovery() is False
    app.bot.get_me = AsyncMock(side_effect=TelegramError("down"))
    bot.tg_bot = app.bot
    assert await module.TelegramBot._probe_bot(bot) is False
    bot.tg_bot = None
    assert await module.TelegramBot._probe_bot(bot) is False

    bot._lifecycle_lock = asyncio.Lock()
    await bot._lifecycle_lock.acquire()
    await bot._recovery_tick()
    bot._lifecycle_lock.release()
    monkeypatch.setattr(bot, "_needs_recovery", AsyncMock(return_value=False))
    await bot._recovery_tick()
    monkeypatch.setattr(bot, "_needs_recovery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot, "config", AsyncMock(side_effect=RuntimeError("rebuild")))
    await bot._recovery_tick()

    bot._closing = False
    bot._ensure_supervisor()
    bot._ensure_supervisor()
    await asyncio.sleep(0.02)
    await bot.shutdown()

    bot._mode = "polling"
    request = Bag(json=AsyncMock(return_value={"update_id": 1}))
    await bot.put_update(request)
    bot._mode = "webhook"
    bot.tg_bot = None
    with pytest.raises(RuntimeError):
        await bot.put_update(request)
    bot.tg_bot = app.bot
    bot.tg_app = app
    app.update_queue = asyncio.Queue()
    monkeypatch.setattr(module.Update, "de_json", staticmethod(lambda payload, tg_bot: Bag(update_id=1)))
    await bot.put_update(request)
    app.update_queue = None
    with pytest.raises(RuntimeError):
        await bot.put_update(request)

    failing = _new_bot(module)
    monkeypatch.setattr(failing, "_configure", AsyncMock(side_effect=RuntimeError("config")))
    monkeypatch.setattr(failing, "_shutdown", AsyncMock())
    with pytest.raises(RuntimeError):
        await failing.config()
    failing._shutdown.assert_awaited()


async def test_install_handlers_registers_expected_groups(bot_module):
    app = FakeApp()
    bot_module.TelegramBot._install_handlers(app)
    assert app.add_handler.called
    assert app.add_error_handler.called
