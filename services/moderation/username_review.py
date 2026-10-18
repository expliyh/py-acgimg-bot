"""Join-time username screening shared by join requests and member updates."""

from __future__ import annotations

import unicodedata

from telegram.error import TelegramError

from . import actions, ai, store

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


def inspect_user(user, policy):
    if not getattr(policy, "username_review_enabled", False):
        return None
    username = (getattr(user, "username", None) or "").strip()
    display_name = (getattr(user, "full_name", None) or "").strip()
    values = [("用户名", username)] if username else []
    if display_name:
        values.append(("显示名", display_name))
    for label, value in values:
        folded = unicodedata.normalize("NFKC", value).casefold()
        for word in getattr(policy, "username_sensitive_words", []) or []:
            if unicodedata.normalize("NFKC", word).casefold() in folded:
                return {"reason": f"{label}命中敏感词：{word}", "kind": "sensitive_word"}
        if getattr(policy, "username_block_emoji", False) and _has_emoji(value):
            return {"reason": f"{label}包含 Emoji", "kind": "emoji"}
        if getattr(policy, "username_block_abnormal_chars", False) and _has_abnormal(value):
            return {"reason": f"{label}包含异常字符", "kind": "abnormal_chars"}
    return None


async def inspect_with_ai(user, policy):
    local = inspect_user(user, policy)
    if local:
        return local
    if not getattr(policy, "username_ai_check", False):
        return None
    config = await store.ai_config()
    if not config.base_url or not config.text_model:
        return None
    value = getattr(user, "username", None) or getattr(user, "full_name", None) or ""
    verdict, _usage = await ai.check_username(config, value)
    if verdict.safe:
        return None
    if not verdict.safe:
        return {"reason": f"AI 用户名检查：{verdict.reason}", "kind": "ai", "confidence": verdict.confidence}
    return None


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


async def reject_member(bot, chat, user, reason: str) -> bool:
    event, fresh = await store.event(
        chat.id,
        "username_review",
        user_id=user.id,
        incident=f"username-join:{user.id}:{getattr(user, 'username', '')}",
        status="running",
        reason=reason,
        data={"username": getattr(user, "username", None), "name": getattr(user, "full_name", None)},
    )
    if not fresh:
        return True
    try:
        await actions.require_right(bot, chat.id, "can_restrict_members")
        from datetime import datetime, timedelta, timezone
        until = datetime.now(timezone.utc) + timedelta(minutes=1)
        await bot.ban_chat_member(chat.id, user.id, until_date=until)
        await bot.unban_chat_member(chat.id, user.id, only_if_banned=True)
        await store.finish_event(event["id"], "success", {"action": "kick", "reason": reason})
    except (ValueError, TelegramError) as exc:
        await store.finish_event(event["id"], "uncertain" if actions.is_uncertain_error(exc) else "failed", {"error": type(exc).__name__})
    return True
