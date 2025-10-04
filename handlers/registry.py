from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar, overload

from telegram.ext import BaseHandler, CommandHandler

Callback = TypeVar("Callback", bound=Callable[..., Awaitable[object]])

MessageCallback = Callable[..., Awaitable[object]]

_registered_handlers: list[BaseHandler] = []
_registered_message_handlers: dict[str, MessageCallback] = {}


@overload
def bot_handler(func: Callback) -> Callback:
    ...


@overload
def bot_handler(
    *,
    commands: str | Sequence[str] | None = None,
    builder: Callable[[Callback], BaseHandler] | None = None,
    **handler_kwargs: Any,
) -> Callable[[Callback], Callback]:
    ...


def bot_handler(
    func: Callback | None = None,
    *,
    commands: str | Sequence[str] | None = None,
    builder: Callable[[Callback], BaseHandler] | None = None,
    **handler_kwargs: Any,
):
    """Register a handler callback via decorator usage.

    By default a :class:`~telegram.ext.CommandHandler` is constructed. Custom builder
    functions may be supplied when other handler types are required.
    """

    def register(callback: Callback) -> Callback:
        handler = _build_handler(
            callback,
            commands=commands,
            builder=builder,
            handler_kwargs=handler_kwargs,
        )
        _registered_handlers.append(handler)
        return callback

    if func is not None:
        return register(func)
    return register



@overload
def message_handler(func: MessageCallback) -> MessageCallback:
    ...


@overload
def message_handler(*, name: str | None = None) -> Callable[[MessageCallback], MessageCallback]:
    ...


def message_handler(
    func: MessageCallback | None = None,
    *,
    name: str | None = None,
) -> MessageCallback | Callable[[MessageCallback], MessageCallback]:
    """Register a message handler callback via decorator usage."""

    def register(callback: MessageCallback) -> MessageCallback:
        handler_name = name or getattr(callback, "__message_handler_name__", None) or callback.__name__
        if not handler_name:
            raise ValueError("Message handler name could not be determined")
        _registered_message_handlers[handler_name] = callback
        return callback

    if func is not None:
        return register(func)
    return register


def iter_message_handlers() -> dict[str, MessageCallback]:
    """Return a snapshot of all registered message handler callbacks keyed by name."""

    return dict(_registered_message_handlers)


def iter_bot_handlers() -> list[BaseHandler]:
    """Return a snapshot of all decorators-registered handlers."""

    return list(_registered_handlers)


def _build_handler(
    callback: Callback,
    *,
    commands: str | Sequence[str] | None,
    builder: Callable[[Callback], BaseHandler] | None,
    handler_kwargs: dict[str, Any],
) -> BaseHandler:
    if builder is not None:
        handler = builder(callback)
        if not isinstance(handler, BaseHandler):
            raise TypeError("Handler builder must return a telegram.ext.BaseHandler instance")
        return handler

    return _build_command_handler(callback, commands=commands, handler_kwargs=handler_kwargs)


def _build_command_handler(
    callback: Callback,
    *,
    commands: str | Sequence[str] | None,
    handler_kwargs: dict[str, Any],
) -> CommandHandler:
    command_names = commands
    if command_names is None:
        command_names = getattr(callback, "__command_name__", None)
    if command_names is None:
        command_names = callback.__name__

    return CommandHandler(command_names, callback, **handler_kwargs)