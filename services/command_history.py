"""Utilities for recording command execution history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import wraps
from typing import Awaitable, Callable, Sequence, TypeVar

from telegram import Update
from telegram.ext import ContextTypes

from registries import command_history_registry

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[object]])


def _safe_truncate(value: str | None, max_length: int = 500) -> str | None:
    if value is None:
        return None
    if len(value) <= max_length:
        return value
    return value[: max_length - 1] + "…"


def command_logger(command_name: str) -> Callable[[F], F]:
    """Decorate a handler to automatically persist command execution details."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            started_at = datetime.now(timezone.utc)
            success = False
            error_message: str | None = None
            try:
                result = await func(update, context, *args, **kwargs)
                success = True
                return result
            except Exception as exc:  # noqa: BLE001 - 需要记录所有异常
                error_message = _safe_truncate(str(exc))
                raise
            finally:
                try:
                    await _persist_history(
                        command_name=command_name,
                        update=update,
                        context=context,
                        success=success,
                        error_message=error_message,
                        started_at=started_at,
                    )
                except Exception:  # pragma: no cover - 日志记录即可
                    logger.exception("Failed to record command history for %s", command_name)

        return wrapper  # type: ignore[return-value]

    return decorator


async def _persist_history(
    *,
    command_name: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    success: bool,
    error_message: str | None,
    started_at: datetime,
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    arguments: Sequence[str] | None = getattr(context, "args", None)
    raw_text = message.text if message and message.text else None

    ended_at = datetime.now(timezone.utc)
    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    await command_history_registry.record_command_execution(
        command=command_name,
        user_id=user.id if user else None,
        chat_id=chat.id if chat else None,
        chat_type=chat.type if chat else None,
        message_id=message.message_id if message else None,
        arguments=arguments,
        raw_text=raw_text,
        success=success,
        error_message=error_message,
        duration_ms=duration_ms,
        triggered_at=started_at,
    )
