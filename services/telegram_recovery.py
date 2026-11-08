"""Retry, deadlines, and forced shutdown for the Telegram client.

python-telegram-bot's httpx timeouts do not always abort a socket whose payload
was accepted by the kernel and then never acknowledged (a dead proxy or a host
that slept). ``Application.stop()`` waits until in-flight handlers finish, and
``TelegramBot.config()`` holds the lifecycle lock across that wait, so one stuck
``send_message`` or ``getUpdates`` also stuck ``/api/bot-tokens/reload``.

Each Bot API call therefore has:

* finite connect, read, write, and pool timeouts, including the separate
  getUpdates client;
* ``TCP_USER_TIMEOUT`` / keepalive so the kernel aborts a silent socket;
* an asyncio deadline that cancels the call if the httpx timeout never fires.

Startup retries transient network errors with backoff. Shutdown is abandoned
after a bounded wait so the lifecycle lock is always released.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from urllib.parse import urlsplit

from telegram._utils.defaultvalue import DefaultValue
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.request import HTTPXRequest

from configs import config

logger = logging.getLogger(__name__)

_ORPHANED_TASKS: set[asyncio.Task] = set()


class StartupAbandoned(Exception):
    """A startup attempt did not finish and could not be cancelled."""


class PollActivity:
    """Last successful getUpdates, ignoring results from a replaced application."""

    def __init__(self) -> None:
        self.generation = 0
        self.last_success_at: float | None = None

    def bump(self) -> int:
        self.generation += 1
        self.last_success_at = None
        return self.generation

    def note(self, generation: int, url: object) -> None:
        if generation != self.generation or not is_get_updates_url(url):
            return
        self.last_success_at = time.monotonic()

    def stalled(self, limit: float) -> bool:
        if self.last_success_at is None:
            return True
        return time.monotonic() - self.last_success_at > limit


def is_get_updates_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    return urlsplit(url).path.rstrip("/").endswith("/getUpdates")


def telegram_method(url: object) -> str:
    """Return the Bot API method name without the token embedded in the URL."""

    if not isinstance(url, str):
        return "telegram"
    name = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return name or "telegram"


def is_transient_network_error(exc: BaseException | None) -> bool:
    """Network failures worth retrying. ``BadRequest`` is a rejected API call."""

    if isinstance(exc, TimeoutError):
        return True
    if not isinstance(exc, NetworkError) or isinstance(exc, BadRequest):
        return False
    return True


def _positive(value: object, fallback: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def _non_negative(value: object, fallback: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def hard_deadline(*parts: float, slack: float) -> float:
    total = sum(part for part in parts if part > 0) + max(slack, 0.0)
    return max(total, 1.0)


def retry_attempts() -> int:
    try:
        count = int(config.telegram_retry_attempts)
    except (TypeError, ValueError):
        return 3
    if count < 1:
        return 3
    return min(count, 20)


def bootstrap_retry_count() -> int:
    try:
        count = int(config.telegram_bootstrap_retries)
    except (TypeError, ValueError):
        return 2
    return max(0, min(count, 20))


def shutdown_timeout() -> float:
    return _positive(config.telegram_shutdown_timeout, 15.0)


def watchdog_interval() -> float:
    return _positive(config.telegram_watchdog_interval, 30.0)


def healthcheck_failure_limit() -> int:
    try:
        count = int(config.telegram_healthcheck_failures)
    except (TypeError, ValueError):
        return 3
    return count if count >= 1 else 3


def polling_timeout() -> float:
    return _positive(config.telegram_polling_timeout, 10.0)


def startup_attempt_timeout() -> float:
    slack = _non_negative(config.telegram_request_hard_slack, 5.0)
    return hard_deadline(
        _positive(config.telegram_connect_timeout, 10.0),
        _positive(config.telegram_read_timeout, 20.0),
        _positive(config.telegram_write_timeout, 20.0),
        _positive(config.telegram_pool_timeout, 5.0),
        slack=slack,
    )


def poll_request_budget() -> float:
    """Longest a single healthy or hung getUpdates is allowed to run."""

    slack = _non_negative(config.telegram_request_hard_slack, 5.0)
    read_margin = _positive(config.telegram_get_updates_read_timeout, 15.0)
    return hard_deadline(
        _positive(config.telegram_get_updates_connect_timeout, 10.0),
        read_margin + polling_timeout(),
        _positive(config.telegram_get_updates_write_timeout, 10.0),
        _positive(config.telegram_get_updates_pool_timeout, 5.0),
        slack=slack,
    )


def poll_stall_limit() -> float:
    configured = _positive(config.telegram_poll_stall_timeout, 120.0)
    return max(configured, poll_request_budget() * 2)


def telegram_socket_options() -> tuple[tuple[int, int, int], ...]:
    """Keepalive plus a user timeout so unacknowledged sends cannot sit forever."""

    options: list[tuple[int, int, int]] = [
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
    ]
    idle_name = "TCP_KEEPIDLE" if hasattr(socket, "TCP_KEEPIDLE") else "TCP_KEEPALIVE"
    idle = getattr(socket, idle_name, None)
    specs = (
        (idle, _positive(config.telegram_tcp_keepidle, 30)),
        (getattr(socket, "TCP_KEEPINTVL", None), _positive(config.telegram_tcp_keepintvl, 10)),
        (getattr(socket, "TCP_KEEPCNT", None), _positive(config.telegram_tcp_keepcnt, 3)),
    )
    for constant, value in specs:
        if constant is None:
            continue
        options.append((socket.IPPROTO_TCP, int(constant), int(value)))
    user_timeout = getattr(socket, "TCP_USER_TIMEOUT", None)
    milliseconds = int(_positive(config.telegram_tcp_user_timeout, 20.0) * 1000)
    if user_timeout is not None and milliseconds > 0:
        options.append((socket.IPPROTO_TCP, int(user_timeout), milliseconds))
    return tuple(options)


def _remember(task: asyncio.Task) -> None:
    _ORPHANED_TASKS.add(task)

    def _discard(done: asyncio.Task) -> None:
        _ORPHANED_TASKS.discard(done)
        with suppress(BaseException):
            done.exception()

    task.add_done_callback(_discard)


def _cancel_task(candidate: object) -> None:
    if isinstance(candidate, asyncio.Task) and not candidate.done():
        candidate.cancel()


async def _wait_for_task(task: asyncio.Task, timeout: float) -> bool:
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    return task in done


async def await_bounded(awaitable: Awaitable, timeout: float, *, label: str) -> bool:
    """Wait until ``awaitable`` finishes. Return False if it had to be abandoned.

    ``asyncio.wait_for`` waits for cancellation to finish. A socket that ignores
    cancellation would keep holding the lifecycle lock, so the wait itself is bounded.
    """

    task = asyncio.ensure_future(awaitable)
    try:
        finished = await _wait_for_task(task, timeout)
    except asyncio.CancelledError:
        task.cancel()
        if not await _wait_for_task(task, 1):
            _remember(task)
        raise
    if finished:
        task.result()
        return True
    logger.error("%s exceeded %.1fs; cancelling it so the caller is not blocked", label, timeout)
    task.cancel()
    if not await _wait_for_task(task, 1):
        logger.error("%s was still running after cancellation; detaching it", label)
        _remember(task)
    return False


async def _close_client(client: object) -> None:
    if client is None or getattr(client, "is_closed", True):
        return
    closer = getattr(client, "aclose", None)
    if closer is None:
        return
    task = asyncio.create_task(closer())
    if await _wait_for_task(task, 2):
        with suppress(Exception):
            task.result()
        return
    task.cancel()
    if not await _wait_for_task(task, 1):
        _remember(task)


async def force_close_application(app: object) -> None:
    """Cancel polling and handler tasks and close HTTP clients without waiting forever."""

    _cancel_task(getattr(app, "_Application__update_fetcher_task", None))
    created = getattr(app, "_Application__create_task_tasks", None)
    if isinstance(created, (set, list, tuple)):
        for task in list(created):
            _cancel_task(task)
    updater = getattr(app, "updater", None)
    if updater is not None:
        with suppress(Exception):
            updater._running = False
        stop_event = getattr(updater, "_Updater__polling_task_stop_event", None)
        if isinstance(stop_event, asyncio.Event):
            stop_event.set()
        _cancel_task(getattr(updater, "_Updater__polling_task", None))
    with suppress(Exception):
        app._running = False  # type: ignore[attr-defined]
    bot = getattr(app, "bot", None)
    requests = getattr(bot, "_request", None) if bot is not None else None
    if not isinstance(requests, tuple):
        return
    await asyncio.gather(
        *(_close_client(getattr(request, "_client", None)) for request in requests),
        return_exceptions=True,
    )


class DeadlineHTTPXRequest(HTTPXRequest):
    """HTTPXRequest that cannot outlive the sum of its configured timeouts."""

    __slots__ = ("_hard_slack", "_on_success", "last_success_at")

    def __init__(
        self,
        *args,
        hard_slack: float = 5.0,
        on_success: Callable[[str], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._hard_slack = hard_slack
        self._on_success = on_success
        self.last_success_at: float | None = None

    def _phase_timeout(self, value: object, fallback: float | None) -> float:
        if isinstance(value, DefaultValue) or value is None:
            if fallback is None:
                return 0.0
            return float(fallback)
        return float(value)

    async def _drop_wedged_client(self) -> None:
        wedged = self._client
        self._client = self._build_client()
        await _close_client(wedged)

    async def do_request(
        self,
        url: str,
        method: str,
        request_data=None,
        read_timeout=HTTPXRequest.DEFAULT_NONE,
        write_timeout=HTTPXRequest.DEFAULT_NONE,
        connect_timeout=HTTPXRequest.DEFAULT_NONE,
        pool_timeout=HTTPXRequest.DEFAULT_NONE,
    ):
        if self._client.is_closed:
            await self.initialize()
        files = request_data.multipart_data if request_data is not None else None
        if isinstance(write_timeout, DefaultValue):
            write_fallback = self._media_write_timeout if files else self._client.timeout.write
        else:
            write_fallback = None
        deadline = hard_deadline(
            self._phase_timeout(connect_timeout, self._client.timeout.connect),
            self._phase_timeout(read_timeout, self._client.timeout.read),
            self._phase_timeout(write_timeout, write_fallback),
            self._phase_timeout(pool_timeout, self._client.timeout.pool),
            slack=self._hard_slack,
        )
        task = asyncio.create_task(
            super().do_request(
                url,
                method,
                request_data=request_data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
            )
        )
        try:
            finished = await _wait_for_task(task, deadline)
        except asyncio.CancelledError:
            task.cancel()
            if not await _wait_for_task(task, 1):
                _remember(task)
            raise
        if finished:
            result = task.result()
            self.last_success_at = time.monotonic()
            if self._on_success is not None:
                try:
                    self._on_success(url)
                except Exception:
                    logger.exception("Telegram request success callback failed")
            return result
        method_name = telegram_method(url)
        logger.error(
            "Telegram %s exceeded the %.1fs hard deadline and was cancelled",
            method_name,
            deadline,
        )
        task.cancel()
        if not await _wait_for_task(task, 1):
            _remember(task)
            await self._drop_wedged_client()
        raise TimedOut(f"Telegram {method_name} exceeded the hard deadline ({deadline:.1f}s)")


def build_api_request() -> DeadlineHTTPXRequest:
    return DeadlineHTTPXRequest(
        connection_pool_size=256,
        connect_timeout=_positive(config.telegram_connect_timeout, 10.0),
        read_timeout=_positive(config.telegram_read_timeout, 20.0),
        write_timeout=_positive(config.telegram_write_timeout, 20.0),
        pool_timeout=_positive(config.telegram_pool_timeout, 5.0),
        media_write_timeout=_positive(config.telegram_media_write_timeout, 60.0),
        socket_options=telegram_socket_options(),
        hard_slack=_non_negative(config.telegram_request_hard_slack, 5.0),
    )


def build_updates_request(on_success: Callable[[str], None]) -> DeadlineHTTPXRequest:
    return DeadlineHTTPXRequest(
        connection_pool_size=1,
        connect_timeout=_positive(config.telegram_get_updates_connect_timeout, 10.0),
        read_timeout=_positive(config.telegram_get_updates_read_timeout, 15.0),
        write_timeout=_positive(config.telegram_get_updates_write_timeout, 10.0),
        pool_timeout=_positive(config.telegram_get_updates_pool_timeout, 5.0),
        socket_options=telegram_socket_options(),
        hard_slack=_non_negative(config.telegram_request_hard_slack, 5.0),
        on_success=on_success,
    )


async def retry_telegram_call(action: Callable[[], Awaitable], description: str):
    """Retry ``action`` on timeout and transport errors. Other errors propagate immediately."""

    attempts = retry_attempts()
    delay = _non_negative(config.telegram_retry_initial_delay, 1.0)
    backoff = _positive(config.telegram_retry_backoff, 2.0)
    max_delay = _non_negative(config.telegram_retry_max_delay, 30.0)
    for attempt in range(1, attempts + 1):
        try:
            return await action()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not is_transient_network_error(exc) or attempt >= attempts:
                raise
            logger.warning(
                "Telegram %s failed (%s: %s); retrying in %.1fs (attempt %s/%s)",
                description,
                type(exc).__name__,
                exc,
                delay,
                attempt,
                attempts,
            )
            if delay:
                await asyncio.sleep(delay)
            delay = min(max_delay, delay * backoff)


async def on_application_error(update: object, context) -> None:
    """Log handler failures. Network errors are not replayed: the call may have landed."""

    error = getattr(context, "error", None)
    update_id = getattr(update, "update_id", None)
    if is_transient_network_error(error):
        logger.error(
            "Telegram handler failed with %s (update_id=%s): %s. "
            "The update was not completed and was not replayed; polling continues.",
            type(error).__name__,
            update_id,
            error,
            exc_info=error if isinstance(error, BaseException) else None,
        )
        return
    logger.error(
        "Telegram handler failed (update_id=%s)",
        update_id,
        exc_info=error if isinstance(error, BaseException) else None,
    )
