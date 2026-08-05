"""Unit tests for the illustration importer helpers."""

from services.illustration_importer import _unique_chat_ids


class TestUniqueChatIds:
    def test_empty_input(self):
        assert _unique_chat_ids(None) == []
        assert _unique_chat_ids([]) == []

    def test_deduplicates_while_preserving_order(self):
        assert _unique_chat_ids([1, 2, 1, 3, 2]) == [1, 2, 3]

    def test_single_chat(self):
        assert _unique_chat_ids([42]) == [42]
