"""Unit tests for small pure helpers."""

from utils import is_group_type
from utils.list_utils import ensure_list_length
from registries.config_registry import _optional_str
from handlers.command_handlers.setu_handler import _parse_pixiv_arguments


class TestIsGroupType:
    def test_group_and_supergroup_are_groups(self):
        assert is_group_type("group") is True
        assert is_group_type("supergroup") is True

    def test_private_and_channel_are_not_groups(self):
        assert is_group_type("private") is False
        assert is_group_type("channel") is False

    def test_unknown_type_is_not_group(self):
        assert is_group_type("anything-else") is False


class TestEnsureListLength:
    def test_list_shorter_than_length_is_padded(self):
        result = ensure_list_length(["a"], 3)
        assert result == ["a", None, None]

    def test_list_longer_than_length_is_kept_untouched(self):
        # list 分支不截断：保持原列表引用与长度
        result = ensure_list_length(["a", "b", "c"], 2)
        assert result == ["a", "b", "c"]

    def test_tuple_longer_than_length_is_truncated(self):
        result = ensure_list_length(("a", "b", "c"), 2)
        assert result == ["a", "b"]

    def test_exact_length_is_kept(self):
        result = ensure_list_length([1, 2], 2)
        assert result == [1, 2]

    def test_tuple_becomes_list(self):
        result = ensure_list_length(("a", "b"), 3)
        assert isinstance(result, list)
        assert result == ["a", "b", None]

    def test_none_returns_filled_list(self):
        result = ensure_list_length(None, 2)
        assert result == [None, None]

    def test_scalar_returns_filled_list(self):
        result = ensure_list_length(42, 3)
        assert result == [None, None, None]


class TestOptionalStr:
    def test_none_stays_none(self):
        assert _optional_str(None) is None

    def test_bool_becomes_string(self):
        assert _optional_str(True) == "True"

    def test_whitespace_only_becomes_none(self):
        assert _optional_str("   ") is None

    def test_text_is_stripped(self):
        assert _optional_str("  value  ") == "value"


class TestParsePixivArguments:
    def test_numeric_argument(self):
        assert _parse_pixiv_arguments(["12345"]) == (12345, None)

    def test_keyword_argument(self):
        assert _parse_pixiv_arguments(["id=12345"]) == (12345, None)

    def test_non_numeric_argument_is_ignored(self):
        assert _parse_pixiv_arguments(["not-a-number"]) == (None, None)

    def test_invalid_id_after_keyword_reports_error(self):
        assert _parse_pixiv_arguments(["id=abc"]) == (None, "id=abc")

    def test_empty_arguments(self):
        assert _parse_pixiv_arguments([]) == (None, None)

    def test_negative_number_is_ignored(self):
        assert _parse_pixiv_arguments(["-5"]) == (None, None)
