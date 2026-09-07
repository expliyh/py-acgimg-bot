"""Bounded rule evaluation and short-lived rate windows."""

import hashlib
import re
import time
import unicodedata
from collections import defaultdict, deque
from urllib.parse import urlparse

import regex

from services import group_guard

from . import store

_windows = defaultdict(deque)
_last_sweep = 0.0


def window(key, seconds: int, value=None) -> list:
    global _last_sweep
    clock = time.monotonic()
    if clock - _last_sweep > 60:
        for old in list(_windows):
            if not _windows[old] or clock - _windows[old][-1][0] > 600:
                del _windows[old]
        _last_sweep = clock
    items = _windows[key]
    while items and items[0][0] <= clock - seconds:
        items.popleft()
    items.append((clock, value))
    while len(items) > 2000:
        items.popleft()
    return [entry[1] for entry in items]


def normalize(text: str) -> str:
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKC", text).casefold()
            if unicodedata.category(c) != "Cf"
        ).split()
    )


def fingerprint(message) -> str:
    parts = [normalize(message.text or message.caption or "")]
    if message.photo:
        parts.append(message.photo[-1].file_unique_id)
    for name in (
        "video",
        "audio",
        "voice",
        "document",
        "sticker",
        "animation",
        "video_note",
    ):
        attachment = getattr(message, name, None)
        if attachment:
            parts.append(attachment.file_unique_id)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def version(message) -> str:
    return hashlib.sha256(
        (
            fingerprint(message)
            + str(message.edit_date or message.date)
            + str(message.entities)
            + str(message.caption_entities)
        ).encode()
    ).hexdigest()


def links(message) -> list[str]:
    text = message.text or message.caption or ""
    result = re.findall(
        r"(?:https?://|www\.)[^\s<>]+|(?:t\.me|telegram\.me)/[^\s<>]+",
        text,
        re.IGNORECASE,
    )
    for entity, value in (
        message.parse_entities() | message.parse_caption_entities()
    ).items():
        if entity.type == "text_link" and entity.url:
            result.append(entity.url)
        elif entity.type == "url":
            result.append(value)
    return result


def host(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    try:
        return (parsed.hostname or "").rstrip(".").encode("idna").decode().lower()
    except (UnicodeError, ValueError):
        return ""


def allowed(url, allowlist) -> bool:
    domain = host(url)
    return any(domain == entry or domain.endswith("." + entry) for entry in allowlist)


def matches(rule: dict, message, allowlist) -> bool:
    kind, pattern = rule["kind"], rule.get("pattern", "")
    text = message.text or message.caption or ""
    if kind == "keyword":
        return (
            pattern in text
            if rule.get("case_sensitive")
            else normalize(pattern) in normalize(text)
        )
    if kind == "regex":
        try:
            return bool(
                regex.search(
                    pattern,
                    text[:16000],
                    flags=0 if rule.get("case_sensitive") else regex.I,
                    timeout=0.02,
                )
            )
        except (regex.error, TimeoutError):
            return False
    if kind in {"link", "invite"}:
        for url in links(message):
            if allowed(url, allowlist):
                continue
            if kind == "link" or (
                host(url) in {"t.me", "telegram.me", "telegram.dog"}
                and re.search(r"/(?:\+|joinchat/)", url)
            ):
                return True
        return False
    if kind == "forward":
        return bool(message.forward_origin)
    if kind == "media":
        return (
            bool(message.media_group_id)
            if pattern == "album"
            else bool(getattr(message, pattern, None))
        )
    return False


async def evaluate(message, settings):
    group_id = message.chat_id
    if settings.keyword_filter_enabled:
        for rule in await group_guard.list_keyword_rules(group_id):
            if matches(
                {
                    "kind": "regex" if rule.is_regex else "keyword",
                    "pattern": rule.pattern,
                    "case_sensitive": rule.case_sensitive,
                },
                message,
                settings.domain_allowlist,
            ):
                return {"reason": f"关键词规则 #{rule.id}", "warn": False}
    if settings.rules_enabled:
        hits = [
            row
            for row in await store.records(group_id, "rule", enabled=True)
            if matches(row["data"], message, settings.domain_allowlist)
        ]
        if hits:
            return {
                "reason": "命中规则 " + ", ".join(row["key"] for row in hits),
                "warn": any(row["data"].get("action") == "delete_warn" for row in hits),
            }
    if settings.flood_enabled and message.from_user and not message.edit_date:
        user_id = message.from_user.id
        count = window((group_id, user_id, "flood"), settings.flood_window)
        repeated = window(
            (group_id, user_id, "repeat"), settings.repeat_window, fingerprint(message)
        )
        if (
            len(count) > settings.flood_limit
            or repeated.count(fingerprint(message)) >= settings.repeat_limit
        ):
            return {"reason": "超过消息频率或重复内容限制", "warn": True}
    return None
