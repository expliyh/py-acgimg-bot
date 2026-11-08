"""Local checks that Telegram would accept generated markup. No network."""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

from utils.telegram_text import utf16_len

_MDV2_SPECIAL = set("_*[]()~`>#+-=|{}.!\\")
_ALLOWED_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "a",
    "code",
    "pre",
    "blockquote",
}
_ENTITY_RE = re.compile(r"&(?:lt|gt|amp|quot|#\d{1,7}|#x[0-9A-Fa-f]{1,6});")
_TAG_RE = re.compile(
    r"</(?P<close>[a-zA-Z0-9-]+)\s*>"
    r"|<(?P<open>[a-zA-Z0-9-]+)(?P<attrs>(?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*=\"[^<\"]*\")*)\s*>"
)


def assert_markdown_v2_escaped(text: str) -> None:
    """The text is valid MarkdownV2 because every reserved character is escaped."""

    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            assert index + 1 < len(text), text
            assert text[index + 1] in _MDV2_SPECIAL, (text[index + 1], index, text)
            index += 2
            continue
        assert char not in _MDV2_SPECIAL, (char, index, text)
        index += 1


def assert_valid_telegram_html(text: str) -> None:
    """Reject markup Telegram's HTML parser would refuse, and over-long messages."""

    assert isinstance(text, str)
    assert utf16_len(text) <= 4096
    index = 0
    stack: list[str] = []
    while index < len(text):
        if text[index] == "&":
            match = _ENTITY_RE.match(text, index)
            assert match is not None, text[index:index + 16]
            index = match.end()
            continue
        if text[index] != "<":
            index += 1
            continue
        match = _TAG_RE.match(text, index)
        assert match is not None, text[index:index + 40]
        if match.group("close"):
            name = match.group("close").lower()
            assert stack and stack[-1] == name, (name, stack)
            stack.pop()
        else:
            name = match.group("open").lower()
            assert name in _ALLOWED_TAGS, name
            attrs = match.group("attrs") or ""
            if name == "a":
                href = re.fullmatch(r'\s+href="([^"]*)"', attrs)
                assert href is not None, attrs
                url = html.unescape(href.group(1))
                assert urlsplit(url).scheme.lower() in {"http", "https", "tg"}, url
                assert "a" not in stack
            else:
                assert attrs == "", attrs
            stack.append(name)
        index = match.end()
    assert stack == []


def visible_text(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def hrefs(text: str) -> list[str]:
    return [html.unescape(value) for value in re.findall(r'href="([^"]*)"', text)]


def legacy_markdown_unclosed_offset(text: str) -> int | None:
    """Byte offset of an unclosed legacy-Markdown entity.

    This follows tdlib ``parse_markdown`` (Bot API ``Markdown``, the mode used
    by ``reply_markdown``). ``_``, ``*``, ````` ``, and ``[`` open an entity that
    must be closed. Characters inside an entity, including ``_`` in a
    ``[text](url)`` URL, are literal. The returned offset is the one Telegram
    reports as ``can't find end of the entity starting at byte offset``.
    """

    size = len(text)
    index = 0
    while index < size:
        char = text[index]
        nxt = text[index + 1] if index + 1 < size else ""
        if char == "\\" and nxt in "_*`[":
            index += 2
            continue
        if char not in "_*`[":
            index += 1
            continue

        begin = index
        end_character = "]" if char == "[" else char
        index += 1
        is_pre = False
        if char == "`" and index + 1 < size and text[index] == "`" and text[index + 1] == "`":
            index += 2
            is_pre = True
            language_end = index
            while language_end < size and not text[language_end].isspace() and text[language_end] != "`":
                language_end += 1
            if index != language_end and language_end < size and text[language_end] != "`":
                index = language_end
            if index < size and text[index] in "\n\r":
                newline = text[index + 1] if index + 1 < size else ""
                if newline in "\n\r" and text[index] != newline:
                    index += 2
                else:
                    index += 1
        while index < size and (
            text[index] != end_character
            or (is_pre and not (index + 2 < size and text[index + 1] == "`" and text[index + 2] == "`"))
        ):
            index += 1
        if index == size:
            return begin
        if char == "[":
            if index + 1 < size and text[index + 1] == "(":
                index += 2
                while index < size and text[index] != ")":
                    index += 1
        if is_pre:
            index += 2
        index += 1
    return None
