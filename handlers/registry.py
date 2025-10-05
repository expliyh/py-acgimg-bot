from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar, overload

from telegram import Update
from telegram.ext import BaseHandler, CommandHandler, MessageHandler, filters as tg_filters, ContextTypes
from telegram.ext.filters import BaseFilter

from handlers.message_handlers.AcgimgMessageHandler import AcgimgMessageHandler

logger = logging.getLogger(__name__)

Callback = TypeVar("Callback", bound=Callable[..., Awaitable[object]])
MessageCallback = Callable[..., Awaitable[object]]

_registered_handlers: list[BaseHandler] = []
_registered_message_handlers: list[AcgimgMessageHandler] = []


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
def message_handler(
        *,
        filters: BaseFilter = tg_filters.ALL,
        no_parallel: bool = True,
        block: bool = False,
        name: str | None = None,
) -> Callable[[MessageCallback], MessageCallback]:
    ...


def message_handler(
        func: MessageCallback | None = None,
        *,
        filters: BaseFilter = tg_filters.ALL,
        no_parallel: bool = True,
        block: bool = False,
        name: str | None = None,
) -> MessageCallback | Callable[[MessageCallback], MessageCallback]:
    """Register a message handler callback via decorator usage."""

    def register(callback: MessageCallback) -> MessageCallback:
        handler_name = name or getattr(callback, "__message_handler_name__", None) or callback.__name__
        if not handler_name:
            raise ValueError("Message handler name could not be determined")

        handler = AcgimgMessageHandler(
            filters=filters,
            callback=callback,
            no_parallel=no_parallel,
            block=block,
        )
        logger.error(f"Registered message handler {handler.callback}")
        _registered_message_handlers.append(handler)
        setattr(callback, "__message_handler_name__", handler_name)
        return callback

    if func is not None:
        return register(func)
    return register


def iter_message_handlers() -> list[AcgimgMessageHandler]:
    """Return a snapshot of all registered telegram message handlers."""

    return list(_registered_message_handlers)


async def message_handler_foreach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register a callback for each registered message handler."""

    pending_list = list()
    for handler in iter_message_handlers():
        logging.info("Checking message handler: %s", handler.callback)
        if handler.check_update(update):
            if handler.no_parallel:
                await asyncio.gather(*pending_list)
                await handler.handle_update(update, context)
            else:
                pending_list.append(asyncio.create_task(handler.handle_update(update, context)))
        if handler.block:
            await asyncio.gather(*pending_list)
            return
    await asyncio.gather(*pending_list)


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
