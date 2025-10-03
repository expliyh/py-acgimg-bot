from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


@dataclass(slots=True)
class OriginalImageRequest:
    token: str
    chat_id: int
    user_id: int
    pixiv_id: int
    page_id: int
    message_id: int | None = None
    attempts: int = 0
    status: str = "ready"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def button_label(self) -> str:
        if self.status == "fetching":
            return "原图获取中"
        if self.status == "success":
            return "原图获取成功"
        if self.status == "exhausted":
            return "原图获取失败"
        if self.attempts > 0:
            return f"重试获取原图 ({self.attempts}/{MAX_ATTEMPTS})"
        return "获取原图"

    def build_markup(self) -> InlineKeyboardMarkup:
        button = InlineKeyboardButton(self.button_label(), callback_data=f"orig:{self.token}")
        return InlineKeyboardMarkup([[button]])


_requests: dict[str, OriginalImageRequest] = {}
_latest_token_by_chat: dict[int, str] = {}
_registry_lock = asyncio.Lock()


def create_request(chat_id: int, user_id: int, pixiv_id: int, page_id: int) -> OriginalImageRequest:
    token = secrets.token_hex(8)
    return OriginalImageRequest(
        token=token,
        chat_id=chat_id,
        user_id=user_id,
        pixiv_id=pixiv_id,
        page_id=page_id,
    )


async def register_request(bot, request: OriginalImageRequest) -> None:
    if request.message_id is None:
        raise ValueError("message_id must be assigned before registering the request")

    previous_state: OriginalImageRequest | None = None
    async with _registry_lock:
        previous_token = _latest_token_by_chat.get(request.chat_id)
        if previous_token is not None and previous_token != request.token:
            previous_state = _requests.pop(previous_token, None)
        _requests[request.token] = request
        _latest_token_by_chat[request.chat_id] = request.token

    if previous_state and previous_state.message_id is not None:
        try:
            await bot.edit_message_reply_markup(
                chat_id=previous_state.chat_id,
                message_id=previous_state.message_id,
                reply_markup=None,
            )
        except TelegramError as exc:
            logger.warning(
                "Failed to remove original image button for chat %s message %s: %s",
                previous_state.chat_id,
                previous_state.message_id,
                exc,
            )


async def get_request(token: str) -> OriginalImageRequest | None:
    async with _registry_lock:
        return _requests.get(token)


async def is_request_active(request: OriginalImageRequest) -> bool:
    async with _registry_lock:
        return _requests.get(request.token) is request


async def update_markup(bot, request: OriginalImageRequest) -> None:
    if request.message_id is None:
        return
    if not await is_request_active(request):
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=request.chat_id,
            message_id=request.message_id,
            reply_markup=request.build_markup(),
        )
    except TelegramError as exc:
        logger.warning(
            "Failed to update original image button for chat %s message %s: %s",
            request.chat_id,
            request.message_id,
            exc,
        )


__all__ = [
    "MAX_ATTEMPTS",
    "OriginalImageRequest",
    "create_request",
    "register_request",
    "get_request",
    "is_request_active",
    "update_markup",
]
