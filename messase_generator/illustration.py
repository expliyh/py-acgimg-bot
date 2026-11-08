"""Telegram HTML for an illustration card.

``/pinfo`` used to send :meth:`models.illustrations.Illustration.get_markdown`
with legacy Markdown. ``**title**`` is not bold in that mode (the stars form
empty entities), and a single ``_``, ``*``, backtick, or ``[`` in the title,
author, tags, or caption is an unclosed entity. Telegram rejects the message
and the command produced no reply.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable

from utils.telegram_text import PARSE_MODE_HTML, escape_html, html_link, safe_http_url, utf16_len

ILLUSTRATION_PARSE_MODE = PARSE_MODE_HTML

_MESSAGE_LIMIT = 4096
_BREAK_TAGS = re.compile(r"(?i)<br\s*/?>|</p\s*>")


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, bytes):
        return []
    if isinstance(value, Iterable):
        return list(value)
    return []


def _tag_names(value: object) -> list[str]:
    names: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            item = item.get("name")
        if item is None:
            continue
        text = str(item).strip()
        if text:
            names.append(text)
    return names


def _caption_text(value: object) -> str:
    """Turn a Pixiv HTML caption into readable plain text before escaping."""

    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _BREAK_TAGS.sub("\n", text)
    return text.strip()


def _page_url(illust: object, index: int) -> str | None:
    """Prefer the Pixiv original URL. ``file_urls`` is empty until import."""

    for attr in ("origin_urls", "file_urls"):
        values = _as_list(getattr(illust, attr, None))
        if index >= len(values):
            continue
        url = values[index]
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _clip_plain(text: str, limit: int) -> str:
    """Return plain text whose HTML-escaped form fits in ``limit`` UTF-16 units."""

    if limit <= 0 or not text:
        return ""
    if utf16_len(escape_html(text)) <= limit:
        return text
    ellipsis = "…"
    ellipsis_cost = utf16_len(escape_html(ellipsis))
    if limit <= ellipsis_cost:
        return ""
    body_limit = limit - ellipsis_cost
    low = 0
    high = len(text)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        if utf16_len(escape_html(text[:mid])) <= body_limit:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    if best <= 0:
        return ""
    return text[:best] + ellipsis


def _original_html(illust: object, page_count: int, page_limit: int) -> str:
    if page_count <= 0 or page_limit <= 0:
        return "原图: 暂无"
    if page_count == 1:
        url = safe_http_url(_page_url(illust, 0))
        if url is None:
            return "原图: 暂无"
        return html_link("原图", url)

    shown = min(page_count, page_limit)
    parts: list[str] = []
    for index in range(shown):
        label = str(index + 1)
        url = safe_http_url(_page_url(illust, index))
        parts.append(html_link(label, url) if url is not None else escape_html(label))
    if shown < page_count:
        parts.append("…")
    return "原图: " + ", ".join(parts)


def _assemble(
    illust: object,
    *,
    title: str,
    author: str,
    tags_text: str,
    caption_text: str,
    page_count: int,
    page_limit: int,
    is_ai: bool,
) -> str:
    source_type = str(getattr(illust, "source_type", "") or "pixiv").strip().lower()
    author_url = getattr(illust, "author_url", None)
    author_id = getattr(illust, "author_id", None)
    if not author_url and source_type == "pixiv" and author_id:
        author_url = f"https://www.pixiv.net/users/{author_id}"
    safe_author_url = safe_http_url(author_url)
    author_html = html_link(author, safe_author_url) if safe_author_url else escape_html(author)

    blocks = [
        f"<b>{escape_html(title)}</b>",
        f"作者: {author_html}",
        f"标签: {escape_html(tags_text) if tags_text else '无'}",
        f"描述: {escape_html(caption_text) if caption_text else '无'}",
        _original_html(illust, page_count, page_limit),
    ]
    source_url = safe_http_url(getattr(illust, "source_url", None))
    if source_url is not None:
        blocks.append(html_link("来源", source_url))
    blocks.append(f"AI: {'是' if is_ai else '否'}")
    return "\n\n".join(blocks)


def render_illustration_html(illust: object) -> str:
    """Return a Telegram HTML card. Send it with parse mode ``HTML``."""

    raw_title = str(getattr(illust, "title", "") or "").strip() or "无题"
    raw_author = str(getattr(illust, "author_name", "") or "").strip() or "未知"
    raw_tags = ", ".join(_tag_names(getattr(illust, "tags", None)))
    raw_caption = _caption_text(getattr(illust, "caption", None))
    try:
        page_count = int(getattr(illust, "page_count", 0) or 0)
    except (TypeError, ValueError):
        page_count = 0
    page_count = max(page_count, 0)
    is_ai = bool(getattr(illust, "is_ai", False))

    title = _clip_plain(raw_title, 500) or "无题"
    author = _clip_plain(raw_author, 500) or "未知"
    tags_text = _clip_plain(raw_tags, 1000)
    caption_text = raw_caption
    page_limit = page_count

    # Shrink caption, then tags, then page links, then the title and author
    # until the escaped message fits. Each branch makes the next attempt smaller.
    for _ in range(page_count + 8):
        text = _assemble(
            illust,
            title=title,
            author=author,
            tags_text=tags_text,
            caption_text=caption_text,
            page_count=page_count,
            page_limit=page_limit,
            is_ai=is_ai,
        )
        if utf16_len(text) <= _MESSAGE_LIMIT:
            return text
        if caption_text:
            clipped = _clip_plain(caption_text, 400)
            caption_text = "" if clipped == caption_text else clipped
            continue
        if tags_text:
            tags_text = ""
            continue
        if page_limit > 0:
            page_limit -= 1
            continue
        if utf16_len(escape_html(title)) > 80:
            title = _clip_plain(title, 80) or "无题"
            continue
        if author != "未知":
            author = "未知"
            continue
        if title != "无题":
            title = "无题"
            continue
        break

    return _assemble(
        illust,
        title="无题",
        author="未知",
        tags_text="",
        caption_text="",
        page_count=page_count,
        page_limit=0,
        is_ai=is_ai,
    )
