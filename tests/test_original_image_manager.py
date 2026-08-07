from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from services import original_image_manager as manager


@pytest.fixture(autouse=True)
def clear_registry():
    manager._requests.clear()
    manager._latest_token_by_chat.clear()


def test_request_labels_and_markup():
    request = manager.OriginalImageRequest("tok", 1, 2, 3, 4)
    assert request.button_label() == "获取原图"
    request.attempts = 1
    assert "1/3" in request.button_label()
    request.status = "fetching"
    assert request.button_label() == "原图获取中"
    request.status = "success"
    assert request.build_markup().inline_keyboard[0][0].callback_data == "orig:tok"
    request.status = "exhausted"
    assert request.button_label() == "原图获取失败"


@pytest.mark.asyncio
async def test_register_replaces_previous_request_and_removes_markup(monkeypatch):
    monkeypatch.setattr(manager.secrets, "token_hex", lambda _: "generated")
    first = manager.OriginalImageRequest("first", 1, 2, 3, 4, message_id=10)
    second = manager.create_request(1, 2, 5, 0)
    second.message_id = 11
    bot = AsyncMock()

    await manager.register_request(bot, first)
    await manager.register_request(bot, second)

    assert second.token == "generated"
    assert await manager.get_request("first") is None
    assert await manager.get_request("generated") is second
    assert await manager.is_request_active(second)
    bot.edit_message_reply_markup.assert_awaited_once_with(chat_id=1, message_id=10, reply_markup=None)


@pytest.mark.asyncio
async def test_register_requires_message_id():
    with pytest.raises(ValueError):
        await manager.register_request(AsyncMock(), manager.create_request(1, 2, 3, 4))


@pytest.mark.asyncio
async def test_update_markup_ignores_inactive_and_telegram_errors():
    bot = AsyncMock()
    inactive = manager.OriginalImageRequest("inactive", 1, 2, 3, 4, message_id=10)
    await manager.update_markup(bot, inactive)
    bot.edit_message_reply_markup.assert_not_awaited()

    await manager.register_request(bot, inactive)
    bot.reset_mock()
    bot.edit_message_reply_markup.side_effect = BadRequest("gone")
    await manager.update_markup(bot, inactive)
    bot.edit_message_reply_markup.assert_awaited_once()
