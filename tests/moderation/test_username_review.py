from types import SimpleNamespace

from services.moderation.username_review import inspect_user


def policy(**overrides):
    values = {
        "username_review_enabled": True,
        "username_sensitive_words": [],
        "username_block_emoji": False,
        "username_block_abnormal_chars": False,
        "username_ai_check": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def user(username=None, full_name="普通用户"):
    return SimpleNamespace(username=username, full_name=full_name)


def test_sensitive_username_is_rejected_case_insensitively():
    hit = inspect_user(user("ScAm_Admin"), policy(username_sensitive_words=["spam"]))
    assert hit and hit["kind"] == "sensitive_word"


def test_emoji_and_decorative_symbols_can_be_blocked():
    assert inspect_user(user("nice😀"), policy(username_block_emoji=True))["kind"] == "emoji"
    assert inspect_user(user("꧁nice꧂"), policy(username_block_abnormal_chars=True))["kind"] == "abnormal_chars"


def test_normal_username_is_allowed():
    assert inspect_user(user("normal_user"), policy(username_block_emoji=True, username_block_abnormal_chars=True)) is None
