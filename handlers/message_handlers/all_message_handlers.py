"""Aggregate all message handler callbacks registered via decorators."""

from handlers.registry import iter_message_handlers

# Import modules for side effects so their handlers register before aggregation.
from . import (
    group_guard,
    guard_add_keyword,
    guard_remove_keyword,
    guard_set_message,
    guard_set_timeout,
    set_backblaze_appid,
    set_cache_redis,
    set_cache_ttl,
    set_pixiv_token,
    set_user_nickname,
)

all_message_handlers = iter_message_handlers()
