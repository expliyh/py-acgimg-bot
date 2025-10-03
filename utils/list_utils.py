from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def ensure_list_length(container: Any, length: int) -> list:
    """Ensure *container* is a list with at least *length* items."""
    if isinstance(container, list):
        if len(container) < length:
            container.extend([None] * (length - len(container)))
        return container
    if isinstance(container, Sequence):
        result = list(container)
        if len(result) < length:
            result.extend([None] * (length - len(result)))
        else:
            result = result[:length]
        return result
    return [None] * length
