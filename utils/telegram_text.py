"""Helpers for Telegram messages that include untrusted text.

Legacy Markdown (``reply_markdown`` / ``ParseMode.MARKDOWN``) treats ``_``,
``*``, ````` ``, and ``[`` as the start of an entity. Illustration titles,
tags, author names, and captions regularly contain those characters, and an
unclosed entity is rejected with ``Can't parse entities``. HTML with escaped
text does not treat them as markup. MarkdownV2 is used only for panels whose
entire body is escaped.
"""

from __future__ import annotations

import html
from urllib.parse import urlsplit

from telegram.helpers import escape_markdown

PARSE_MODE_HTML = "HTML"
PARSE_MODE_MARKDOWN_V2 = "MarkdownV2"

_HTTP_SCHEMES = {"http", "https", "tg"}


def escape_html(text: object, *, quote: bool = False) -> str:
    """Escape text for Telegram HTML. Attribute values must pass ``quote=True``."""

    return html.escape("" if text is None else str(text), quote=quote)


def escape_markdown_v2(text: object) -> str:
    """Escape an entire MarkdownV2 line, including text that has no formatting."""

    return escape_markdown("" if text is None else str(text), version=2)


def parse_mode_kwargs(parse_mode: str | None) -> dict[str, str]:
    """Keyword arguments that opt into a parse mode.

    ``None`` omits the parameter so Telegram receives the text as-is. Passing
    an explicit null is unnecessary and would fight a future bot-wide default
    only when a caller actually sets one; plain panels stay unparsed because
    their generators leave ``parse_mode`` empty.
    """

    if not parse_mode:
        return {}
    return {"parse_mode": parse_mode}


def safe_http_url(url: object) -> str | None:
    """Return ``url`` when it is safe to place in an HTML ``href``."""

    if not isinstance(url, str):
        return None
    candidate = url.strip()
    if not candidate or len(candidate) > 2000:
        return None
    if any(ord(char) < 32 or char in " <>\"'" for char in candidate):
        return None
    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in _HTTP_SCHEMES:
        return None
    if scheme != "tg" and not parts.netloc:
        return None
    return candidate


def html_link(label: object, url: str) -> str:
    """Build an HTML anchor. ``url`` must already have passed :func:`safe_http_url`."""

    return f'<a href="{escape_html(url, quote=True)}">{escape_html(label)}</a>'


def utf16_len(text: str) -> int:
    """Length in UTF-16 code units, which is what Telegram's message limit uses."""

    return len(text.encode("utf-16-le")) // 2
