"""Utilities to persist chat metadata and history for incoming messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from telegram import Chat, Message, Update, User as TgUser
from telegram.ext import ContextTypes

from defines import MessageType
from models import Group, GroupChatHistory, PrivateChatHistory, User
from registries import engine
from services.telegram_cache import get_cached_admin_ids
from utils import is_group_type

logger = logging.getLogger(__name__)

TEXT_PREVIEW_LIMIT = 120


def _preview_text(text: str | None, limit: int = TEXT_PREVIEW_LIMIT) -> str | None:
    if not text:
        return None

    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized

    return normalized[:limit] + "..."


@dataclass(slots=True)
class ParsedMessage:
    """A normalized representation of the details we persist."""

    message_type: MessageType
    text: str | None
    file_id: str | None
    keyboard: dict | list | None


async def log_message_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point that records metadata and history for the provided update."""

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if message is None or chat is None or user is None:
        return

    parsed = _parse_message(message)
    if parsed is None:
        return

    bot_send = bool(user.is_bot)

    if is_group_type(chat.type):
        admin_ids = await _get_admin_ids(context, chat.id)
        await _store_group_message(
            chat=chat,
            user=user,
            message=message,
            parsed=parsed,
            bot_send=bot_send,
            admin_ids=admin_ids,
        )
    elif chat.type == Chat.PRIVATE:
        await _store_private_message(
            user=user,
            message=message,
            parsed=parsed,
            bot_send=bot_send,
        )
    else:
        logger.debug("Ignoring unsupported chat type: %s", chat.type)


async def _store_group_message(
    *,
    chat: Chat,
    user: TgUser,
    message: Message,
    parsed: ParsedMessage,
    bot_send: bool,
    admin_ids: Sequence[int] | None,
) -> None:
    async with engine.new_session() as session:
        db_user = await session.get(User, user.id)
        if db_user is None:
            db_user = User(id=user.id)
            session.add(db_user)
            logger.debug("Created new user record user_id=%s during group message logging", user.id)
        _sync_user_profile(db_user, user)

        db_group = await session.get(Group, chat.id)
        if db_group is None:
            db_group = Group(id=chat.id)
            session.add(db_group)
            logger.debug("Created new group record chat_id=%s during message logging", chat.id)
        _sync_group_profile(db_group, chat, admin_ids)

        await session.merge(
            GroupChatHistory(
                message_id=message.message_id,
                group_id=chat.id,
                user_id=db_user.id,
                type=parsed.message_type,
                bot_send=bot_send,
                file_id=parsed.file_id,
                text=parsed.text,
                key_board=parsed.keyboard,
                sent_at=message.date,
            )
        )

        await session.commit()
        logger.debug(
            "Persisted group message chat_id=%s message_id=%s type=%s bot_send=%s text=%s",
            chat.id,
            message.message_id,
            parsed.message_type,
            bot_send,
            _preview_text(parsed.text),
        )


async def _store_private_message(
    *,
    user: TgUser,
    message: Message,
    parsed: ParsedMessage,
    bot_send: bool,
) -> None:
    async with engine.new_session() as session:
        db_user = await session.get(User, user.id)
        if db_user is None:
            db_user = User(id=user.id)
            session.add(db_user)
            logger.debug("Created new user record user_id=%s during private message logging", user.id)
        _sync_user_profile(db_user, user)

        await session.merge(
            PrivateChatHistory(
                message_id=message.message_id,
                user_id=db_user.id,
                type=parsed.message_type,
                bot_send=bot_send,
                file_id=parsed.file_id,
                text=parsed.text,
                key_board=parsed.keyboard,
                sent_at=message.date,
            )
        )

        await session.commit()
        logger.debug(
            "Persisted private message user_id=%s message_id=%s type=%s bot_send=%s text=%s",
            user.id,
            message.message_id,
            parsed.message_type,
            bot_send,
            _preview_text(parsed.text),
        )


def _sync_user_profile(db_user: User, tg_user: TgUser) -> None:
    """Ensure the stored user profile mirrors the latest Telegram data."""

    nickname = _extract_user_display_name(tg_user)
    if nickname != db_user.nick_name:
        logger.debug("Updating nickname for user_id=%s to %r", db_user.id, nickname)
        db_user.nick_name = nickname


def _sync_group_profile(db_group: Group, chat: Chat, admin_ids: Sequence[int] | None) -> None:
    """Update stored group metadata based on the latest chat information."""

    if chat.title and chat.title != db_group.name:
        logger.debug("Updating group %s title to %r", db_group.id, chat.title)
        db_group.name = chat.title

    if admin_ids is not None and _admin_list_changed(db_group.admin_ids, admin_ids):
        logger.debug("Updating group %s admin ids to %s", db_group.id, list(admin_ids))
        db_group.admin_ids = list(admin_ids)


def _parse_message(message: Message) -> ParsedMessage | None:
    """Determine message type, extract text, file references and keyboard data."""

    message_type = _detect_message_type(message)
    if message_type is None:
        logger.debug("Skipping message_id=%s: unsupported content", message.message_id)
        return None

    text = message.text or message.caption
    file_id = _extract_file_id(message)
    keyboard = message.reply_markup.to_dict() if message.reply_markup else None

    if message.new_chat_members:
        joined_names = ", ".join(_extract_user_display_name(user) for user in message.new_chat_members)
        text = f"New members: {joined_names}" if joined_names else text
    elif message.left_chat_member:
        left_name = _extract_user_display_name(message.left_chat_member)
        text = f"Left member: {left_name}" if left_name else text
    elif message.new_chat_title:
        text = f"New chat title: {message.new_chat_title}"
    elif message.pinned_message:
        pinned = message.pinned_message
        pinned_text = pinned.text or pinned.caption
        if pinned_text:
            text = f"Pinned message: {pinned_text}"

    return ParsedMessage(
        message_type=message_type,
        text=text,
        file_id=file_id,
        keyboard=keyboard,
    )


def _detect_message_type(message: Message) -> MessageType | None:
    if message.text:
        return MessageType.TEXT
    if message.photo:
        return MessageType.PHOTO
    if message.video:
        return MessageType.VIDEO
    if message.animation:
        return MessageType.ANIMATION
    if message.audio:
        return MessageType.AUDIO
    if message.voice:
        return MessageType.VOICE
    if message.document:
        return MessageType.DOCUMENT
    if message.sticker:
        return MessageType.STICKER
    if message.contact:
        return MessageType.CONTACT
    if message.location:
        return MessageType.LOCATION
    if message.venue:
        return MessageType.VENUE
    if message.video_note:
        return MessageType.VIDEO_NOTE
    if message.invoice:
        return MessageType.INVOICE
    if message.successful_payment:
        return MessageType.SUCCESSFUL_PAYMENT
    if message.game:
        return MessageType.GAME
    if message.poll:
        return MessageType.POLL
    if message.dice:
        return MessageType.DICE
    if message.new_chat_members:
        return MessageType.NEW_CHAT_MEMBERS
    if message.left_chat_member:
        return MessageType.LEFT_CHAT_MEMBER
    if message.new_chat_title:
        return MessageType.NEW_CHAT_TITLE
    if message.new_chat_photo:
        return MessageType.NEW_CHAT_PHOTO
    if message.delete_chat_photo:
        return MessageType.DELETE_CHAT_PHOTO
    if message.group_chat_created:
        return MessageType.GROUP_CHAT_CREATED
    if message.supergroup_chat_created:
        return MessageType.SUPERGROUP_CHAT_CREATED
    if message.channel_chat_created:
        return MessageType.CHANNEL_CHAT_CREATED
    if message.migrate_to_chat_id:
        return MessageType.MIGRATE_TO_CHAT_ID
    if message.migrate_from_chat_id:
        return MessageType.MIGRATE_FROM_CHAT_ID
    if message.pinned_message:
        return MessageType.PINNED_MESSAGE
    if message.connected_website:
        return MessageType.CONNECTED_WEBSITE
    if message.passport_data:
        return MessageType.PASSPORT_DATA
    if message.proximity_alert_triggered:
        return MessageType.PROXIMITY_ALERT_TRIGGERED
    if message.voice_chat_scheduled:
        return MessageType.VOICE_CHAT_SCHEDULED
    if message.voice_chat_started:
        return MessageType.VOICE_CHAT_STARTED
    if message.voice_chat_ended:
        return MessageType.VOICE_CHAT_ENDED
    if message.voice_chat_participants_invited:
        return MessageType.VOICE_CHAT_PARTICIPANTS_INVITED
    if message.message_auto_delete_timer_changed:
        return MessageType.MESSAGE_AUTO_DELETE_TIMER_CHANGED

    return MessageType.UNKNOWN


def _extract_file_id(message: Message) -> str | None:
    if message.photo:
        return message.photo[-1].file_id
    if message.video:
        return message.video.file_id
    if message.animation:
        return message.animation.file_id
    if message.audio:
        return message.audio.file_id
    if message.voice:
        return message.voice.file_id
    if message.document:
        return message.document.file_id
    if message.sticker:
        return message.sticker.file_id
    if message.video_note:
        return message.video_note.file_id

    return None


def _extract_user_display_name(user: TgUser | None) -> str | None:
    if user is None:
        return None
    if user.full_name:
        return user.full_name
    if user.username:
        return user.username
    return user.first_name or user.last_name


async def _get_admin_ids(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> list[int] | None:
    """Fetch administrator IDs for a group chat using the shared cache service."""

    admin_ids = await get_cached_admin_ids(context, chat_id)
    if admin_ids is None:
        logger.debug("Admin IDs unavailable for chat %s", chat_id)
    return admin_ids


def _admin_list_changed(existing: Iterable[int] | None, new_list: Sequence[int]) -> bool:
    existing_sorted = sorted(existing or [])
    new_sorted = sorted(new_list)
    return existing_sorted != new_sorted
