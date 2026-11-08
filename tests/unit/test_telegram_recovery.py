"""Retry, deadlines, and self-healing for the Telegram bot. No network."""

import asyncio
import logging
import socket
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.request import HTTPXRequest

from configs import _env_float, _env_int, config
from services.telegram_recovery import (
    DeadlineHTTPXRequest,
    PollActivity,
    hard_deadline,
    is_transient_network_error,
    on_application_error,
    poll_request_budget,
    poll_stall_limit,
    retry_telegram_call,
    telegram_socket_options,
)


def _instant_retry(monkeypatch) -> None:
    monkeypatch.setattr(config, "telegram_retry_attempts", 3)
    monkeypatch.setattr(config, "telegram_retry_initial_delay", 0)
    monkeypatch.setattr(config, "telegram_retry_max_delay", 0)
    monkeypatch.setattr(config, "telegram_retry_backoff", 2)
    monkeypatch.setattr(config, "telegram_watchdog_interval", 60)
    monkeypatch.setattr(config, "telegram_bootstrap_retries", 2)


class _FakeWorker:
    def __init__(self, bot):
        self.bot = bot
        self.running = False

    async def start(self):
        self.running = True

    async def stop(self):
        self.running = False


def _scripted_app():
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.id = 1
    app.bot.get_me = AsyncMock()
    app.bot.delete_webhook = AsyncMock()
    app.bot.set_webhook = AsyncMock()
    app.bot.get_my_commands = AsyncMock(return_value=[])
    app.bot.delete_my_commands = AsyncMock()
    app.bot.set_my_commands = AsyncMock()
    app.bot.shutdown = AsyncMock()
    app.initialize = AsyncMock()
    app.start = AsyncMock()
    app.stop = AsyncMock()
    app.shutdown = AsyncMock()
    app.running = False
    app.updater = MagicMock()
    app.updater.running = False
    app.updater.start_polling = AsyncMock()
    app.updater.stop = AsyncMock()
    app.update_queue = asyncio.Queue()
    return app


class _Builder:
    def __init__(self):
        self.apps = []
        self.api_requests = []
        self.update_requests = []

    def token(self, value):
        self.token_value = value
        return self

    def request(self, request):
        self.api_requests.append(request)
        return self

    def get_updates_request(self, request):
        self.update_requests.append(request)
        return self

    def build(self):
        app = _scripted_app()
        self.apps.append(app)
        return app


@pytest.fixture
def builder(monkeypatch):
    import bot as module

    built = _Builder()
    monkeypatch.setattr(module, "ApplicationBuilder", lambda: built)
    monkeypatch.setattr("services.moderation.worker.Worker", _FakeWorker)
    monkeypatch.setattr("services.image_push.ImagePushWorker", _FakeWorker)
    _instant_retry(monkeypatch)
    monkeypatch.setattr(module.config_registry, "get_bot_tokens", AsyncMock(
        return_value=[SimpleNamespace(enable=True, token="123:test")]
    ))
    return built


@pytest.fixture
async def telegram_bot(builder):
    import bot as module

    bot = module.TelegramBot()
    try:
        yield bot
    finally:
        await bot.shutdown()


def test_invalid_timeout_env_falls_back(monkeypatch):
    monkeypatch.setenv("TELEGRAM_READ_TIMEOUT", "not-a-number")
    monkeypatch.setenv("TELEGRAM_RETRY_ATTEMPTS", "4")
    assert _env_float("TELEGRAM_READ_TIMEOUT", 20.0) == 20.0
    assert _env_int("TELEGRAM_RETRY_ATTEMPTS", 3) == 4


def test_hard_deadline_adds_every_phase_and_slack():
    assert hard_deadline(10, 20, 20, 5, slack=5) == 60
    assert hard_deadline(0, -1, slack=0) == 1


def test_poll_stall_limit_is_at_least_two_long_polls(monkeypatch):
    monkeypatch.setattr(config, "telegram_poll_stall_timeout", 1)
    assert poll_stall_limit() == poll_request_budget() * 2
    monkeypatch.setattr(config, "telegram_poll_stall_timeout", 10_000)
    assert poll_stall_limit() == 10_000


def test_socket_options_enable_keepalive_and_user_timeout(monkeypatch):
    monkeypatch.setattr(config, "telegram_tcp_user_timeout", 12.5)
    options = telegram_socket_options()
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in options
    if hasattr(socket, "TCP_USER_TIMEOUT"):
        user_timeout = [item for item in options if item[1] == socket.TCP_USER_TIMEOUT]
        assert user_timeout == [(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 12_500)]


def test_transient_errors_exclude_rejected_api_calls():
    assert is_transient_network_error(NetworkError("httpx.ConnectError: refused"))
    assert is_transient_network_error(TimedOut("slow"))
    assert is_transient_network_error(TimeoutError())
    assert not is_transient_network_error(BadRequest("chat not found"))
    assert not is_transient_network_error(RuntimeError("boom"))


async def test_retry_succeeds_after_transient_failures(monkeypatch):
    _instant_retry(monkeypatch)
    calls = 0

    async def action():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise NetworkError("httpx.ConnectError: [SSL: WRONG_VERSION_NUMBER]")
        return "ok"

    assert await retry_telegram_call(action, "initialize") == "ok"
    assert calls == 3


async def test_retry_stops_on_a_rejected_request(monkeypatch):
    _instant_retry(monkeypatch)
    calls = 0

    async def action():
        nonlocal calls
        calls += 1
        raise BadRequest("chat not found")

    with pytest.raises(BadRequest):
        await retry_telegram_call(action, "send")
    assert calls == 1


async def test_retry_gives_up_after_the_configured_attempts(monkeypatch):
    _instant_retry(monkeypatch)
    monkeypatch.setattr(config, "telegram_retry_attempts", 2)
    calls = 0

    async def action():
        nonlocal calls
        calls += 1
        raise TimedOut("still down")

    with pytest.raises(TimedOut):
        await retry_telegram_call(action, "initialize")
    assert calls == 2


def test_poll_activity_ignores_stale_generations_and_other_methods():
    activity = PollActivity()
    generation = activity.bump()
    activity.note(generation, "https://api.telegram.org/bot123:SECRET/getUpdates")
    assert activity.last_success_at is not None
    activity.bump()
    activity.note(generation, "https://api.telegram.org/bot123:SECRET/getUpdates")
    assert activity.last_success_at is None
    activity.note(activity.generation, "https://api.telegram.org/bot123:SECRET/sendMessage")
    assert activity.last_success_at is None
    assert activity.stalled(120)


async def test_request_hard_deadline_cancels_a_hung_call_without_logging_the_token(
    monkeypatch, caplog
):
    async def hang(self, *args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(HTTPXRequest, "do_request", hang)
    request = DeadlineHTTPXRequest(
        connect_timeout=0.05,
        read_timeout=0.05,
        write_timeout=0.05,
        pool_timeout=0.05,
        hard_slack=0.05,
    )
    started = time.monotonic()
    url = "https://api.telegram.org/bot123:SECRET/sendMessage"
    with caplog.at_level(logging.ERROR):
        with pytest.raises(TimedOut):
            await request.do_request(url, "POST")
    assert time.monotonic() - started < 1.5
    assert "123:SECRET" not in caplog.text
    assert "sendMessage" in caplog.text
    await request.shutdown()


async def test_successful_get_updates_is_reported(monkeypatch):
    async def ok(self, *args, **kwargs):
        return 200, b"{}"

    monkeypatch.setattr(HTTPXRequest, "do_request", ok)
    seen = []
    request = DeadlineHTTPXRequest(
        connect_timeout=1,
        read_timeout=1,
        write_timeout=1,
        pool_timeout=1,
        hard_slack=1,
        on_success=seen.append,
    )
    url = "https://api.telegram.org/bot123:SECRET/getUpdates"
    await request.do_request(url, "POST")
    assert seen == [url]
    assert request.last_success_at is not None
    await request.shutdown()


async def test_start_reply_retries_a_timeout(monkeypatch):
    import bot as module

    _instant_retry(monkeypatch)
    send_message = AsyncMock(side_effect=[TimedOut("dead socket"), None])
    update = SimpleNamespace(effective_user="user", effective_chat=SimpleNamespace(id=5))
    context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
    await module.start(update, context)
    assert send_message.await_count == 2
    assert send_message.await_args.kwargs["chat_id"] == 5
    assert send_message.await_args.kwargs["text"] == "Hello!"


async def test_handler_network_errors_are_logged_and_not_described_as_replayed(caplog):
    update = SimpleNamespace(update_id=9)
    context = SimpleNamespace(error=TimedOut("send hung"))
    with caplog.at_level(logging.ERROR):
        await on_application_error(update, context)
    assert "update_id=9" in caplog.text
    assert "TimedOut" in caplog.text
    assert "not replayed" in caplog.text
    assert "polling continues" in caplog.text


async def test_initialize_retries_a_transient_network_error(telegram_bot, builder):
    builder.apps.clear()
    app = None

    original_build = builder.build

    def build_and_fail_once():
        nonlocal app
        app = original_build()
        app.initialize = AsyncMock(side_effect=[
            NetworkError("httpx.ConnectError: [SSL: WRONG_VERSION_NUMBER]"),
            None,
        ])
        return app

    builder.build = build_and_fail_once
    await telegram_bot.config()
    assert app.initialize.await_count == 2
    assert telegram_bot._app_initialized is True
    assert telegram_bot._mode == "polling"


async def test_non_network_initialize_failure_is_not_retried_and_disables_the_bot(
    telegram_bot, builder
):
    app = _scripted_app()
    app.initialize = AsyncMock(side_effect=RuntimeError("rejected"))
    builder.build = lambda: app
    await telegram_bot.config()
    assert app.initialize.await_count == 1
    assert telegram_bot.tg_app is None
    assert telegram_bot._app_initialized is False


async def test_polling_keeps_pending_updates_and_retries_bootstrap(telegram_bot, builder, caplog):
    await telegram_bot.config()
    app = builder.apps[-1]
    app.bot.delete_webhook.assert_awaited_with(drop_pending_updates=False)
    kwargs = app.updater.start_polling.await_args.kwargs
    assert kwargs["drop_pending_updates"] is False
    assert kwargs["bootstrap_retries"] == 2
    assert not asyncio.iscoroutinefunction(kwargs["error_callback"])
    with caplog.at_level(logging.ERROR):
        kwargs["error_callback"](NetworkError("httpx.ConnectError: [SSL: WRONG_VERSION_NUMBER]"))
    assert "WRONG_VERSION_NUMBER" in caplog.text
    assert "keep retrying" in caplog.text
    assert telegram_bot._mode == "polling"
    api = builder.api_requests[-1]
    updates = builder.update_requests[-1]
    assert api.read_timeout == config.telegram_read_timeout
    assert updates.read_timeout == config.telegram_get_updates_read_timeout
    assert updates._client_kwargs["limits"].max_connections == 1


async def test_webhook_mode_keeps_pending_updates(telegram_bot, builder, monkeypatch):
    import bot as module

    monkeypatch.setattr(module.config, "external_url", "https://example.test/base/")
    monkeypatch.setattr(module.config, "telegram_webhook_secret", "s3cret")
    await telegram_bot.config()
    app = builder.apps[-1]
    app.updater.start_polling.assert_not_awaited()
    app.bot.set_webhook.assert_awaited()
    args, kwargs = app.bot.set_webhook.await_args
    assert args[0] == "https://example.test/base/tapi/"
    assert kwargs["drop_pending_updates"] is False
    assert kwargs["secret_token"] == "s3cret"
    assert telegram_bot._mode == "webhook"


async def test_shutdown_returns_when_stop_hangs(monkeypatch):
    import bot as module

    monkeypatch.setattr(config, "telegram_shutdown_timeout", 0.2)
    monkeypatch.setattr(config, "telegram_watchdog_interval", 60)
    app = _scripted_app()
    app.running = True
    app.updater.running = True

    async def hang():
        await asyncio.Event().wait()

    app.updater.stop = hang
    bot = module.TelegramBot()
    bot.tg_app = app
    bot.tg_bot = app.bot
    bot._app_initialized = True
    bot._mode = "polling"
    started = time.monotonic()
    await bot.shutdown()
    assert time.monotonic() - started < 2
    assert bot.tg_app is None
    assert bot._app_initialized is False
    assert bot._supervisor_task is None


async def test_reload_returns_when_the_previous_application_stop_hangs(
    telegram_bot, builder, monkeypatch
):
    monkeypatch.setattr(config, "telegram_shutdown_timeout", 0.2)
    hung = _scripted_app()
    hung.running = True
    hung.updater.running = True

    async def hang():
        await asyncio.Event().wait()

    hung.updater.stop = hang
    telegram_bot.tg_app = hung
    telegram_bot.tg_bot = hung.bot
    telegram_bot._app_initialized = True
    telegram_bot._mode = "polling"
    started = time.monotonic()
    await telegram_bot.config()
    assert time.monotonic() - started < 2
    assert telegram_bot.tg_app is builder.apps[-1]
    assert telegram_bot._mode == "polling"
    assert telegram_bot.tg_app is not hung


async def test_needs_recovery_for_token_stall_and_health_probe(telegram_bot, monkeypatch):
    import bot as module

    monkeypatch.setattr(config, "telegram_healthcheck_failures", 3)
    monkeypatch.setattr(
        module.config_registry,
        "get_bot_tokens",
        AsyncMock(return_value=[]),
    )
    assert await telegram_bot._needs_recovery() is False

    monkeypatch.setattr(
        module.config_registry,
        "get_bot_tokens",
        AsyncMock(return_value=[SimpleNamespace(enable=True, token="123:test")]),
    )
    assert await telegram_bot._needs_recovery() is True

    app = _scripted_app()
    app.running = True
    app.updater.running = True
    telegram_bot.tg_app = app
    telegram_bot.tg_bot = app.bot
    telegram_bot._app_initialized = True
    telegram_bot._mode = "polling"
    telegram_bot._poll_activity.last_success_at = time.monotonic() - 10_000
    assert await telegram_bot._needs_recovery() is True
    app.bot.get_me.assert_not_awaited()

    telegram_bot._poll_activity.last_success_at = time.monotonic()
    assert await telegram_bot._needs_recovery() is False
    app.bot.get_me.assert_awaited()

    app.bot.get_me = AsyncMock(side_effect=TimedOut("wedged pool"))
    telegram_bot._mode = "webhook"
    telegram_bot._health_failures = 0
    assert await telegram_bot._needs_recovery() is False
    assert await telegram_bot._needs_recovery() is False
    assert telegram_bot._health_failures == 2
    assert await telegram_bot._needs_recovery() is True


async def test_recovery_tick_rebuilds_only_when_needed_and_the_lock_is_free(telegram_bot):
    calls = 0

    async def rebuild():
        nonlocal calls
        calls += 1

    telegram_bot.config = rebuild
    telegram_bot._needs_recovery = AsyncMock(return_value=False)
    await telegram_bot._recovery_tick()
    assert calls == 0

    telegram_bot._needs_recovery = AsyncMock(return_value=True)
    await telegram_bot._lifecycle_lock.acquire()
    try:
        await telegram_bot._recovery_tick()
    finally:
        telegram_bot._lifecycle_lock.release()
    assert calls == 0

    await telegram_bot._recovery_tick()
    assert calls == 1


async def test_shutdown_does_not_wait_for_the_watchdog_interval(monkeypatch):
    import bot as module

    monkeypatch.setattr(config, "telegram_watchdog_interval", 60)
    bot = module.TelegramBot()
    bot._ensure_supervisor()
    started = time.monotonic()
    await bot.shutdown()
    assert time.monotonic() - started < 2
    assert bot._supervisor_task is None


async def test_later_recovery_brings_a_disabled_bot_back(telegram_bot, builder):
    attempts = {"count": 0}
    app = _scripted_app()

    async def initialize():
        attempts["count"] += 1
        if attempts["count"] <= 3:
            raise TimedOut("getMe timed out")

    app.initialize = initialize
    builder.build = lambda: app
    await telegram_bot.config()
    assert telegram_bot._app_initialized is False
    assert attempts["count"] == 3

    await telegram_bot.config()
    assert attempts["count"] == 4
    assert telegram_bot._app_initialized is True
    assert telegram_bot._mode == "polling"
