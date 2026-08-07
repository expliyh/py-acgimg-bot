from datetime import datetime, timedelta, timezone

import pytest
from telegram import Chat

from services.group_guard import PendingVerification, _ensure_timezone, generate_token
from services.schema_migrator import _build_comment_clause, _build_default_clause, _quote
from services.storage_service.Storage import Storage
from utils.is_group_type import is_group_type
from utils.list_utils import ensure_list_length


def test_ensure_list_length_mutates_lists_and_pads_tuples():
    original = [1]
    assert ensure_list_length(original, 3) is original
    assert original == [1, None, None]
    assert ensure_list_length((1, 2, 3), 2) == [1, 2]
    assert ensure_list_length(object(), 2) == [None, None]


@pytest.mark.parametrize("chat_type", [Chat.GROUP, Chat.SUPERGROUP])
def test_is_group_type(chat_type):
    assert is_group_type(chat_type) is True


def test_private_chat_is_not_group():
    assert is_group_type(Chat.PRIVATE) is False


def test_storage_path_helpers():
    assert Storage.normalize_sub_folder(r"/foo\bar/") == "foo/bar/"
    assert Storage.join_path("/root/", "", r"child\file") == "root/child/file"


def test_schema_sql_helpers_escape_values_and_reject_identifiers():
    assert _quote("safe_table_1") == "`safe_table_1`"
    with pytest.raises(ValueError):
        _quote("users; DROP TABLE users")
    assert _build_default_clause(None) == ""
    assert _build_default_clause(b"abc") == " DEFAULT 'abc'"
    assert _build_default_clause("NULL") == " DEFAULT NULL"
    assert _build_default_clause("it's") == " DEFAULT 'it''s'"
    assert _build_default_clause(3) == " DEFAULT 3"
    assert _build_comment_clause(None) == ""
    assert _build_comment_clause("owner's") == " COMMENT 'owner''s'"


def test_pending_verification_expiry_handles_naive_datetimes():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pending = PendingVerification(1, 2, None, "token", datetime(2026, 1, 1))
    assert pending.is_expired(now=now)
    assert _ensure_timezone(now.astimezone(timezone(timedelta(hours=8)))) == now


def test_generate_token_uses_requested_length_and_alphanumeric_characters():
    token = generate_token(24)
    assert len(token) == 24
    assert token.isalnum()
