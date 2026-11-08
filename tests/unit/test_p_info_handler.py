"""`/pinfo` replies for special titles and for ids Telegram or Pixiv reject."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut

from handlers.command_handlers import p_info_handler
from models.illustrations import Illustration
from services.pixiv_service import PixivWorkNotFound
from tests.unit.telegram_markup import assert_valid_telegram_html, visible_text


def _illustration() -> Illustration:
    return Illustration(
        id="55",
        title="title_*[`]<b>",
        author_id="7",
        author_name="author_*[`]",
        page_count=1,
        sanity_level=2,
        r18g=False,
        x_restrict=0,
        tags=["tag_*[`]", "a<b>&"],
        caption="caption_*[`]<br />next",
        is_ai=False,
        file_urls=[None],
        compressed_file_ids=[None],
        original_file_ids=[None],
        origin_urls=["https://i.pximg.net/img-original/img/55_p0.jpg"],
        file_ext=[".jpg"],
        source_type="pixiv",
    )


def _update(reply):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        message=SimpleNamespace(reply_text=reply, message_id=10),
    )


async def _run(monkeypatch, args, reply, *, fetch=None, enabled=True):
    monkeypatch.setattr(p_info_handler, "has_super_user_access", AsyncMock(return_value=True))
    monkeypatch.setattr(p_info_handler.pixiv, "enabled", enabled)
    fetch = fetch if fetch is not None else AsyncMock(return_value=_illustration())
    monkeypatch.setattr(p_info_handler.pixiv, "get_illust_info_by_pixiv_id", fetch)
    await p_info_handler.p_info_func.__wrapped__(_update(reply), SimpleNamespace(args=args))
    return fetch


async def test_pinfo_sends_html_for_special_characters(monkeypatch):
    reply = AsyncMock()
    fetch = await _run(monkeypatch, ["55"], reply)

    fetch.assert_awaited_once_with(55)
    sent = reply.await_args.kwargs
    assert sent["parse_mode"] == ParseMode.HTML == p_info_handler.ILLUSTRATION_PARSE_MODE
    assert sent["reply_to_message_id"] == 10
    assert_valid_telegram_html(sent["text"])
    visible = visible_text(sent["text"])
    assert "title_*[`]<b>" in visible
    assert "author_*[`]" in visible
    assert "tag_*[`]" in visible
    assert "a<b>&" in visible
    assert reply.await_count == 1


@pytest.mark.parametrize("arg", ["abc", "0", "-5", "12.5", "id=55", "55_1"])
async def test_pinfo_rejects_invalid_ids_without_calling_pixiv(monkeypatch, arg):
    reply = AsyncMock()
    fetch = await _run(monkeypatch, [arg], reply)

    fetch.assert_not_awaited()
    text = reply.await_args.kwargs["text"]
    assert "Pixiv" in text
    assert "parse_mode" not in reply.await_args.kwargs


async def test_pinfo_missing_work_gets_a_not_found_reply(monkeypatch):
    reply = AsyncMock()
    fetch = AsyncMock(side_effect=PixivWorkNotFound(404))
    await _run(monkeypatch, ["404"], reply, fetch=fetch)

    assert "未找到" in reply.await_args.kwargs["text"]
    assert "parse_mode" not in reply.await_args.kwargs


async def test_pinfo_fetch_failure_does_not_leak_the_exception(monkeypatch):
    reply = AsyncMock()
    fetch = AsyncMock(side_effect=RuntimeError("refresh token secret"))
    await _run(monkeypatch, ["55"], reply, fetch=fetch)

    text = reply.await_args.kwargs["text"]
    assert "获取插画信息失败" in text
    assert "secret" not in text
    assert "parse_mode" not in reply.await_args.kwargs


async def test_pinfo_bad_request_gets_a_plain_error_reply(monkeypatch):
    reply = AsyncMock(
        side_effect=[
            BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 35"),
            None,
        ]
    )
    await _run(monkeypatch, ["55"], reply)

    assert reply.await_count == 2
    fallback = reply.await_args_list[1].kwargs
    assert "parse_mode" not in fallback
    assert fallback["text"] == "插画信息发送失败，请稍后再试。"
    assert "byte offset" not in fallback["text"]


async def test_pinfo_timeout_is_not_followed_by_an_error_reply(monkeypatch):
    reply = AsyncMock(side_effect=TimedOut("timed out"))
    with pytest.raises(TimedOut):
        await _run(monkeypatch, ["55"], reply)
    assert reply.await_count == 1


async def test_pinfo_retry_after_still_sends_an_error_reply(monkeypatch):
    reply = AsyncMock(side_effect=[RetryAfter(3), None])
    await _run(monkeypatch, ["55"], reply)
    assert reply.await_count == 2
    assert "发送失败" in reply.await_args_list[1].kwargs["text"]


async def test_pinfo_render_failure_still_replies(monkeypatch):
    reply = AsyncMock()

    class Broken:
        def get_markdown(self):
            raise RuntimeError("render blew up")

    await _run(monkeypatch, ["55"], reply, fetch=AsyncMock(return_value=Broken()))
    assert reply.await_args.kwargs["text"] == "插画信息发送失败，请稍后再试。"
    assert "blew up" not in reply.await_args.kwargs["text"]
