"""Default words are seeded once; runtime reads only the persisted list."""

import asyncio
from types import SimpleNamespace

import pytest

from services.moderation import store, username_review
from services.moderation.schemas import Policy, UsernameReviewConfig


async def test_initialization_persists_defaults_once_and_reads_do_not_seed():
    assert (await store.username_config()).sensitive_words == []
    assert await store.record(0, "username_config", "default") is None
    await asyncio.gather(store.ensure_username_config(), store.ensure_username_config())
    row = await store.record(0, "username_config", "default")
    assert row is not None
    words = row["data"]["sensitive_words"]
    assert 0 < len(words) <= 15
    assert {"USDT", "上门", "注册", "兼职"} <= set(words)
    await store.ensure_username_config()
    assert await store.record(0, "username_config", "default") == row


@pytest.mark.parametrize("words", [["customword"], []])
async def test_reinitialization_preserves_saved_list_and_never_adds_hidden_defaults(words):
    await store.ensure_username_config()
    await store.save_username_config(UsernameReviewConfig(sensitive_words=words))
    await store.ensure_username_config()
    assert (await store.username_config()).sensitive_words == words
    assert (await store.record(0, "username_config", "default"))["data"] == {"sensitive_words": words}
    settings = Policy(username_review_enabled=True)
    assert await username_review.inspect_with_ai(SimpleNamespace(username="USDT"), settings) is None
    assert bool(await username_review.inspect_with_ai(SimpleNamespace(username="customword"), settings)) == bool(words)


async def test_initialization_does_not_overwrite_a_concurrent_save():
    await asyncio.gather(
        store.ensure_username_config(),
        store.save_username_config(UsernameReviewConfig(sensitive_words=["customword"])),
        store.ensure_username_config(),
    )
    assert (await store.username_config()).sensitive_words == ["customword"]
