"""Shared validation and normalization helpers for illustration metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


# Identity, page information, storage URLs and Telegram cache IDs deliberately
# stay outside this set.  They are managed by the import pipeline rather than
# by the gallery editor.
EDITABLE_ILLUSTRATION_FIELDS: tuple[str, ...] = (
    "title",
    "author_name",
    "author_url",
    "source_url",
    "caption",
    "tags",
    "sanity_level",
    "x_restrict",
    "r18g",
    "is_ai",
)

_STRING_FIELDS = {
    "title",
    "author_name",
    "author_url",
    "source_url",
    "caption",
}


def normalize_tags(value: Any) -> list[str]:
    """Normalize tags while preserving the user's order and removing repeats."""

    if value is None:
        return []
    if isinstance(value, str):
        values = value.replace("，", ",").replace("、", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def normalize_edit_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a safe, storage-ready partial update.

    Presence of a key is significant: ``None`` clears nullable string fields,
    while omitted keys are left untouched by callers.
    """

    normalized: dict[str, Any] = {}
    for field in EDITABLE_ILLUSTRATION_FIELDS:
        if field not in values:
            continue
        value = values[field]
        if field in _STRING_FIELDS:
            if value is None:
                normalized[field] = None
            else:
                text = str(value).strip()
                normalized[field] = text or None
        elif field == "tags":
            normalized[field] = normalize_tags(value)
        else:
            normalized[field] = value
    return normalized
