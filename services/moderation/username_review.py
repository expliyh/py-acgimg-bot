"""Join-time username screening shared by join requests and member updates."""

from __future__ import annotations

import hashlib
import unicodedata
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from telegram.error import TelegramError

from models import GuardRecord, GuardTask
from registries import engine

from . import actions, ai, store

REMOVAL_NOTICE = "有用户因用户名审核未通过，已被移出群聊。"
SERVICE_RETENTION_SECONDS = 47 * 3600
AI_REJECTION_CONFIDENCE = 0.9


async def _queue_service_cleanup(group_id, user_id, *, target_message_id=None):
    """Called under the group lock; queue each known message atomically once."""
    service = await store.record(group_id, "username_service", str(user_id))
    if not service:
        return False
    async with engine.new_session() as session:
        removal = await session.scalar(select(GuardRecord).where(
            GuardRecord.group_id == group_id,
            GuardRecord.kind == "username_removal",
            GuardRecord.key == str(user_id),
        ))
        if not removal or removal.data.get("state") not in {"removed", "uncertain"}:
            return False
        data = dict(removal.data)
        queued = set(data.get("queued_ids", []))
        matched = False
        clock = store.now().replace(tzinfo=timezone.utc).timestamp()
        for message in service["data"].get("messages", []):
            stamp = message["timestamp"]
            belongs = (
                message["kind"] == "join"
                and abs(stamp - data["joined_at"]) <= 2
                or message["kind"] == "leave"
                and message["bot_actor"]
                and data["joined_at"] <= stamp <= data["removed_at"] + 60
            )
            if not belongs or clock - stamp >= SERVICE_RETENTION_SECONDS:
                continue
            message_id = message["message_id"]
            matched |= target_message_id is None or message_id == target_message_id
            if message_id in queued:
                continue
            # Several rejected members may share one batch join service message.
            job_id = hashlib.sha256(f"username-service:{group_id}:{message_id}".encode()).hexdigest()[:32]
            if not await session.get(GuardTask, job_id):
                session.add(GuardTask(
                    id=job_id, group_id=group_id, kind="delete", state="pending",
                    due_at=store.now(), created_at=store.now(),
                    data={"message_id": message_id},
                ))
            queued.add(message_id)
        removal.data = data | {"queued_ids": sorted(queued)}
        await session.commit()
        return matched


async def track_service_message(bot, message):
    """Remember service IDs before moderation, including late Telegram updates."""
    members = [(user, "join") for user in message.new_chat_members or []]
    if message.left_chat_member:
        members.append((message.left_chat_member, "leave"))
    targeted = False
    async with store.lock(message.chat.id):
        for user, kind in members:
            row = await store.record(message.chat.id, "username_service", str(user.id))
            clock = store.now().replace(tzinfo=timezone.utc).timestamp()
            messages = [item for item in (row or {}).get("data", {}).get("messages", [])
                        if clock - item["timestamp"] < SERVICE_RETENTION_SECONDS]
            if not any(item["message_id"] == message.message_id for item in messages):
                messages.append({
                    "message_id": message.message_id,
                    "timestamp": message.date.timestamp(), "kind": kind,
                    "bot_actor": bool(message.from_user and message.from_user.id == bot.id),
                })
            await store.put_record(message.chat.id, "username_service", str(user.id),
                                   {"messages": messages[-20:]})
            targeted |= await _queue_service_cleanup(
                message.chat.id, user.id, target_message_id=message.message_id
            )
    return targeted


_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2300, 0x23FF),
    (0x2B00, 0x2BFF),
)


def _has_emoji(value: str) -> bool:
    return any(start <= ord(char) <= end for char in value for start, end in _EMOJI_RANGES)


def _has_abnormal(value: str) -> bool:
    # Telegram usernames are normally ASCII letters, digits and underscores.
    # Keep ordinary Unicode letters/numbers useful for display-name fallback,
    # while rejecting invisible controls and decorative symbols/punctuation.
    for char in value:
        category = unicodedata.category(char)
        if category.startswith("C") or category.startswith("S"):
            return True
        if category.startswith("P") and char not in "_.-":
            return True
    return False


def inspect_user(user, policy, global_words=()):
    if not getattr(policy, "username_review_enabled", False):
        return None
    username = (getattr(user, "username", None) or "").strip()
    display_name = (getattr(user, "full_name", None) or "").strip()
    values = [("用户名", username)] if username else []
    if display_name:
        values.append(("显示名", display_name))
    for label, value in values:
        folded = unicodedata.normalize("NFKC", value).casefold()
        for word in (*global_words, *(getattr(policy, "username_sensitive_words", []) or [])):
            needle = unicodedata.normalize("NFKC", word).casefold().strip()
            if needle and needle in folded:
                return {"reason": f"{label}命中敏感词：{word}", "kind": "sensitive_word"}
        if getattr(policy, "username_block_emoji", False) and _has_emoji(value):
            return {"reason": f"{label}包含 Emoji", "kind": "emoji"}
        if getattr(policy, "username_block_abnormal_chars", False) and _has_abnormal(value):
            return {"reason": f"{label}包含异常字符", "kind": "abnormal_chars"}
    return None


async def inspect_with_ai(user, policy):
    if not getattr(policy, "username_review_enabled", False):
        return None
    global_config = await store.username_config()
    local = inspect_user(user, policy, global_config.sensitive_words)
    if local:
        return local
    if not getattr(policy, "username_ai_check", False):
        return None
    config = await store.ai_config()
    if not config.base_url or not config.text_model:
        return None
    username = (getattr(user, "username", None) or "").strip()
    display_name = (getattr(user, "full_name", None) or "").strip()
    # Bound each field independently so a long name cannot hide the other one.
    value = f"用户名：{username[:128]}\n显示名：{display_name[:256]}"
    verdict, _usage = await ai.check_username(config, value)
    if verdict.safe or verdict.confidence < AI_REJECTION_CONFIDENCE:
        return None
    return {"reason": f"AI 用户名检查：{verdict.reason}", "kind": "ai", "confidence": verdict.confidence}


async def reject_request(bot, request, reason: str) -> bool:
    group_id = request.chat.id
    event, fresh = await store.event(
        group_id,
        "username_review",
        user_id=request.from_user.id,
        incident=f"username:{request.from_user.id}:{int(request.date.timestamp())}",
        status="running",
        reason=reason,
        data={"username": request.from_user.username, "name": request.from_user.full_name},
    )
    if not fresh:
        return True
    try:
        await actions.require_right(bot, group_id, "can_invite_users")
        await bot.decline_chat_join_request(group_id, request.from_user.id)
        await store.finish_event(event["id"], "success", {"action": "decline", "reason": reason})
    except (ValueError, TelegramError) as exc:
        await store.finish_event(event["id"], "uncertain" if actions.is_uncertain_error(exc) else "failed", {"error": type(exc).__name__})
    return True


async def reject_member(bot, chat, user, reason: str, *, joined_at=None, lock_held=False) -> bool:
    async with (nullcontext() if lock_held else store.lock(chat.id)):
        return await _reject_member(bot, chat, user, reason, joined_at=joined_at)


async def _reject_member(bot, chat, user, reason, *, joined_at):
    joined_at = joined_at or datetime.now(timezone.utc)
    event, fresh = await store.event(
        chat.id,
        "username_review",
        user_id=user.id,
        incident=f"username-join:{user.id}:{joined_at.timestamp()}",
        status="running",
        reason=reason,
        data={"username": getattr(user, "username", None), "name": getattr(user, "full_name", None)},
    )
    if not fresh:
        return True
    previous = await store.record(chat.id, "username_removal", str(user.id))
    removal = {
        "joined_at": joined_at.timestamp(),
        "removed_at": datetime.now(timezone.utc).timestamp(),
        "state": "applying", "queued_ids": (previous or {}).get("data", {}).get("queued_ids", []),
    }
    try:
        if user.id == bot.id or await actions.is_admin(bot, chat.id, user.id):
            raise ValueError("不能移出管理员或本机器人")
        await actions.require_right(bot, chat.id, "can_restrict_members")
        await store.put_record(chat.id, "username_removal", str(user.id), removal)
        until = datetime.now(timezone.utc) + timedelta(minutes=1)
        await bot.ban_chat_member(chat.id, user.id, until_date=until)
    except (ValueError, TelegramError) as exc:
        status = "uncertain" if actions.is_uncertain_error(exc) else "failed"
        await store.put_record(chat.id, "username_removal", str(user.id), removal | {"state": status})
        await store.finish_event(event["id"], status, {"error": type(exc).__name__})
        return True

    await store.put_record(chat.id, "username_removal", str(user.id), removal | {"state": "removed"})
    await _queue_service_cleanup(chat.id, user.id)
    # A confirmed ban removed the user even if the subsequent unban fails.
    # Claim the notice before sending; an ambiguous send is never replayed.
    notice, fresh_notice = await store.event(
        chat.id, "username_notice", user_id=user.id,
        incident=event["id"], status="running",
    )
    if fresh_notice:
        try:
            await bot.send_message(chat.id, REMOVAL_NOTICE, parse_mode=None)
            await store.finish_event(notice["id"], "success", {})
        except TelegramError as exc:
            await store.finish_event(notice["id"], "uncertain" if actions.is_uncertain_error(exc) else "failed", {"error": type(exc).__name__})
    try:
        await bot.unban_chat_member(chat.id, user.id, only_if_banned=True)
        await store.finish_event(event["id"], "success", {"action": "kick", "reason": reason})
    except TelegramError as exc:
        await store.finish_event(event["id"], "uncertain" if actions.is_uncertain_error(exc) else "failed", {"ban": "success", "error": type(exc).__name__})
    return True
