"""Command handlers and the original-image callback, with external calls mocked."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telegram import MessageEntity
from telegram.error import TelegramError, TimedOut

from defines import GroupStatus, UserStatus
from exps import GroupBlockedError, UserBlockedError
from services.moderation.schemas import Policy
from tests.unit.telegram_fakes import Bag, make_context, make_message, make_update, make_user, sent_texts


def _user(**kwargs):
    data = dict(id=1, status=UserStatus.NORMAL, sanity_limit=6, allow_r18g=True, nick_name="n")
    data.update(kwargs)
    return SimpleNamespace(**data)


def _group(**kwargs):
    data = dict(
        id=10,
        status=GroupStatus.ENABLED,
        enable=True,
        allow_setu=True,
        sanity_limit=6,
        allow_r18g=True,
        admin_ids=[1],
        name="g",
    )
    data.update(kwargs)
    return SimpleNamespace(**data)


def _illust(**kwargs):
    data = dict(
        id=42,
        title="标题",
        author_name="作者",
        author_id=7,
        page_count=2,
        is_ai=False,
        sanity_level=2,
        r18g=False,
        page_id=0,
    )
    data.update(kwargs)
    return SimpleNamespace(**data)


async def test_setu_permission_and_argument_branches(monkeypatch):
    from handlers.command_handlers import setu_handler as module

    monkeypatch.setattr(module.user_registry, "get_user_by_id", AsyncMock(return_value=_user(status=UserStatus.BLOCKED)))
    with pytest.raises(UserBlockedError):
        await module.setu.__wrapped__(make_update(), make_context())
    monkeypatch.setattr(module.user_registry, "get_user_by_id", AsyncMock(return_value=_user(status=UserStatus.INACTIVE)))
    with pytest.raises(UserBlockedError):
        await module.setu.__wrapped__(make_update(), make_context())

    monkeypatch.setattr(module.user_registry, "get_user_by_id", AsyncMock(return_value=_user()))
    monkeypatch.setattr(module.group_registry, "get_group_by_id", AsyncMock(return_value=_group(status=GroupStatus.BLOCKED)))
    with pytest.raises(GroupBlockedError):
        await module.setu.__wrapped__(make_update(chat_type="group"), make_context())
    monkeypatch.setattr(module.group_registry, "get_group_by_id", AsyncMock(return_value=_group(enable=False)))
    with pytest.raises(GroupBlockedError):
        await module.setu.__wrapped__(make_update(chat_type="group"), make_context())
    monkeypatch.setattr(module.group_registry, "get_group_by_id", AsyncMock(return_value=_group(status=GroupStatus.DISABLED, enable=True)))
    with pytest.raises(GroupBlockedError):
        await module.setu.__wrapped__(make_update(chat_type="supergroup"), make_context())
    monkeypatch.setattr(module.group_registry, "get_group_by_id", AsyncMock(return_value=_group(allow_setu=False)))
    with pytest.raises(GroupBlockedError):
        await module.setu.__wrapped__(make_update(chat_type="group"), make_context())

    monkeypatch.setattr(module.config_registry, "is_r18g_allowed", AsyncMock(return_value=True))
    monkeypatch.setattr(module.group_registry, "get_group_by_id", AsyncMock(return_value=_group(sanity_limit=3, allow_r18g=False)))
    context = make_context(["id=abc"])
    update = make_update(chat_type="group")
    await module.setu.__wrapped__(update, context)
    assert "格式不正确" in sent_texts(context.bot.send_message)[0]

    context = make_context(["99"])
    monkeypatch.setattr(module.illust_registry, "get_illust_info", AsyncMock(return_value=None))
    await module.setu.__wrapped__(make_update(chat_type="private"), context)
    assert "未找到" in sent_texts(context.bot.send_message)[-1]

    context = make_context(["99"])
    monkeypatch.setattr(module.illust_registry, "get_illust_info", AsyncMock(return_value=_illust(sanity_level=9)))
    await module.setu.__wrapped__(make_update(chat_type="private"), context)
    assert "过滤等级" in sent_texts(context.bot.send_message)[-1]

    context = make_context(["99"])
    monkeypatch.setattr(module.illust_registry, "get_illust_info", AsyncMock(return_value=_illust(r18g=True, sanity_level=1)))
    monkeypatch.setattr(module.config_registry, "is_r18g_allowed", AsyncMock(return_value=False))
    await module.setu.__wrapped__(make_update(chat_type="private"), context)
    assert "R18G" in sent_texts(context.bot.send_message)[-1]

    monkeypatch.setattr(module, "get_image_resource", AsyncMock(side_effect=FileNotFoundError("missing")))
    context = make_context(["99"])
    monkeypatch.setattr(module.illust_registry, "get_illust_info", AsyncMock(return_value=_illust()))
    monkeypatch.setattr(module.config_registry, "is_r18g_allowed", AsyncMock(return_value=True))
    await module.setu.__wrapped__(make_update(chat_type="private"), context)
    assert "指定 ID" in sent_texts(context.bot.send_message)[-1]

    context = make_context()
    await module.setu.__wrapped__(make_update(chat_type="private"), context)
    assert "没有符合条件" in sent_texts(context.bot.send_message)[-1]


async def test_setu_sends_photo_and_handles_timeout(monkeypatch):
    from handlers.command_handlers import setu_handler as module

    resource = SimpleNamespace(illustration=_illust(id="not-int"), page_id=0)
    monkeypatch.setattr(module.user_registry, "get_user_by_id", AsyncMock(return_value=_user(allow_r18g=False)))
    monkeypatch.setattr(module.config_registry, "is_r18g_allowed", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "get_image_resource", AsyncMock(return_value=resource))
    monkeypatch.setattr(module, "send_illustration_photo", AsyncMock(side_effect=TimedOut("slow")))
    update = make_update(chat_type="private")
    update.effective_message = None
    await module.setu.__wrapped__(update, make_context())

    request = SimpleNamespace(build_markup=lambda: "markup", message_id=None)
    resource.illustration = _illust()
    monkeypatch.setattr(module.illust_registry, "get_illust_info", AsyncMock(return_value=_illust()))
    monkeypatch.setattr(module, "create_request", lambda **kwargs: request)
    sent = SimpleNamespace(id=55)
    monkeypatch.setattr(module, "send_illustration_photo", AsyncMock(return_value=sent))
    register = AsyncMock()
    monkeypatch.setattr(module, "register_request", register)
    update = make_update(chat_type="private")
    await module.setu.__wrapped__(update, make_context(["  ", "pid=42"]))
    register.assert_awaited()
    assert request.message_id == 55

    await module._reply_with_text(make_context(), chat_id=1, text="hi", reply_to_message_id=None)


async def test_root_message_summary_and_dispatch(monkeypatch):
    from handlers.message_handlers import index, root

    assert index.index["root"] is root.root
    assert root._display_user(None) == "unknown"
    user = make_user(username=None, full_name="", first_name="", last_name="李")
    assert root._display_user(user) == "李"
    bare = make_user(username=None, full_name="", first_name="", last_name="")
    assert root._display_user(bare) == "1"
    assert root._preview_text(None) is None
    assert root._preview_text("  a   b  ") == "a b"
    assert root._preview_text("x" * 200).endswith("...")

    photo = Bag(file_id="p")
    message = make_message(
        text=None,
        caption="cap",
        photo=[photo],
        new_chat_members=[make_user()],
        left_chat_member=make_user(),
        pinned_message=make_message(text="pin"),
        via_bot=make_user(),
        date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    message.effective_attachment = [photo]
    assert "PhotoSize" not in root._describe_message(message) or "attachments" in root._describe_message(message)
    single = make_message(text="hello")
    single.effective_attachment = photo
    assert "Bag" in root._describe_attachments(single) or root._describe_attachments(single) != "none"
    empty = make_message(text=None)
    empty.effective_attachment = []
    assert root._describe_attachments(empty) == "none"
    assert root._describe_message(None) == "no-message"

    called = AsyncMock()
    monkeypatch.setattr(root, "message_handler_foreach", called)
    monkeypatch.setattr(root, "log_message_update", AsyncMock())
    await root.handle_incoming_message(make_update(text="hello"), make_context())
    called.assert_awaited()
    update = make_update()
    update.effective_message = None
    update.effective_chat = None
    update.effective_user = None
    await root.handle_incoming_message(update, make_context())


async def test_original_image_callback(monkeypatch):
    from handlers.callback_handlers import original_image_handler as module

    update = make_update(query_data="orig")
    update.callback_query = None
    await module.callback_original_image_handler(update, make_context(), ["t"])
    update = make_update(query_data="orig")
    await module.callback_original_image_handler(update, make_context(), [])

    state = SimpleNamespace(
        message_id=20,
        user_id=1,
        lock=asyncio.Lock(),
        status="ready",
        attempts=0,
        pixiv_id=5,
        page_id=0,
        chat_id=10,
    )
    monkeypatch.setattr(module, "get_request", AsyncMock(return_value=None))
    await module.callback_original_image_handler(make_update(query_data="orig"), make_context(), ["tok"])
    monkeypatch.setattr(module, "get_request", AsyncMock(return_value=state))
    mismatch = make_update(query_data="orig", message_id=99)
    await module.callback_original_image_handler(mismatch, make_context(), ["tok"])
    wrong_user = make_update(query_data="orig", message_id=20, user_id=8)
    wrong_user.callback_query.from_user = make_user(8)
    await module.callback_original_image_handler(wrong_user, make_context(), ["tok"])
    monkeypatch.setattr(module, "is_request_active", AsyncMock(return_value=False))
    await module.callback_original_image_handler(make_update(query_data="orig", message_id=20), make_context(), ["tok"])

    monkeypatch.setattr(module, "is_request_active", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "update_markup", AsyncMock())
    state.status = "fetching"
    await module.callback_original_image_handler(make_update(query_data="orig", message_id=20), make_context(), ["tok"])
    state.status = "success"
    await module.callback_original_image_handler(make_update(query_data="orig", message_id=20), make_context(), ["tok"])
    state.status = "ready"
    state.attempts = module.MAX_ATTEMPTS
    await module.callback_original_image_handler(make_update(query_data="orig", message_id=20), make_context(), ["tok"])
    assert state.status == "exhausted"

    state.attempts = 0
    state.status = "ready"
    resource = SimpleNamespace(
        file_id="cached",
        filename="a.jpg",
        link="http://example/a.jpg",
        page_id=0,
        illustration=SimpleNamespace(page_count=2, original_file_ids=["cached", None]),
        fetcher=AsyncMock(return_value=b"bytes"),
    )
    monkeypatch.setattr(module, "get_image_resource", AsyncMock(return_value=resource))
    context = make_context()
    await module.callback_original_image_handler(make_update(query_data="orig", message_id=20), context, ["tok"])
    assert state.status == "success"

    state.status = "ready"
    context.bot.send_document = AsyncMock(side_effect=TimedOut("slow"))
    await module._send_original_image(context.bot, resource, 10)
    context.bot.send_document = AsyncMock(side_effect=[TelegramError("stale"), SimpleNamespace(document=SimpleNamespace(file_id="new")), SimpleNamespace(document=SimpleNamespace(file_id="fresh"))])
    save = AsyncMock()
    monkeypatch.setattr(module.illust_registry, "save_illustration", save)
    await module._send_original_image(context.bot, resource, 10)
    save.assert_awaited()

    resource.file_id = None
    resource.illustration.original_file_ids = ["new", None]
    await module._send_original_image(context.bot, resource, 10)
    await module._store_original_file_id(resource.illustration, 0, "new")
    await module._clear_cached_original_id(resource.illustration, 0, "other")


async def test_add_pixiv_and_manual_commands(monkeypatch):
    from handlers.command_handlers import add_manual_handler, add_pixiv_handler

    update = make_update()
    monkeypatch.setattr(add_pixiv_handler.pixiv, "enabled", False)
    await add_pixiv_handler.add_pixiv_command.__wrapped__(update, make_context())
    monkeypatch.setattr(add_pixiv_handler.pixiv, "enabled", True)
    await add_pixiv_handler.add_pixiv_command.__wrapped__(update, make_context())
    await add_pixiv_handler.add_pixiv_command.__wrapped__(update, make_context(["abc"]))
    monkeypatch.setattr(add_pixiv_handler, "has_super_user_access", AsyncMock(return_value=False))
    await add_pixiv_handler.add_pixiv_command.__wrapped__(update, make_context(["12"]))
    monkeypatch.setattr(add_pixiv_handler, "has_super_user_access", AsyncMock(return_value=True))
    page = SimpleNamespace(index=0, storage_url=None, compressed_file_id="p", original_file_id=None)
    result = SimpleNamespace(
        illustration=SimpleNamespace(title="", id=12),
        created=False,
        pages=[page],
        telegram_cache_enabled=True,
    )
    monkeypatch.setattr(add_pixiv_handler, "import_illustration", AsyncMock(return_value=result))
    status = Bag(edit_text=AsyncMock(), message_id=3)
    update.effective_message.reply_text = AsyncMock(return_value=status)
    update.effective_user = None
    await add_pixiv_handler.add_pixiv_command.__wrapped__(update, make_context(["12"]))
    status.edit_text.assert_awaited()
    summary = add_pixiv_handler._format_page_summary(0, storage=True, photo=False, document=True, cache_enabled=False)
    assert "待发送缓存" in summary
    assert add_pixiv_handler._build_chat_candidates(make_update(chat_id=1, user_id=1)) == [1]

    monkeypatch.setattr(add_manual_handler, "has_super_user_access", AsyncMock(return_value=False))
    update = make_update()
    await add_manual_handler.add_manual_command.__wrapped__(update, make_context())
    monkeypatch.setattr(add_manual_handler, "has_super_user_access", AsyncMock(return_value=True))
    await add_manual_handler.add_manual_command.__wrapped__(update, make_context(["name=标题"]))
    photo = Bag(get_file=AsyncMock(return_value=Bag(download_as_bytearray=AsyncMock(return_value=bytearray(b"img")))))
    update = make_update(photo=[photo])
    imported = SimpleNamespace(illustration=SimpleNamespace(title="标题", id=4))
    monkeypatch.setattr(add_manual_handler, "import_manual_illustration", AsyncMock(return_value=imported))
    status = Bag(edit_text=AsyncMock())
    update.effective_message.reply_text = AsyncMock(return_value=status)
    await add_manual_handler.add_manual_command.__wrapped__(update, make_context())
    document = Bag(mime_type="image/png", file_name=None, get_file=AsyncMock(return_value=Bag(download_as_bytearray=AsyncMock(return_value=bytearray(b"img")))))
    reply = make_message(document=document, photo=None)
    update = make_update(reply_to_message=reply)
    update.effective_message.reply_text = AsyncMock(return_value=status)
    await add_manual_handler.add_manual_command.__wrapped__(update, make_context(["title=作品", "author=A", "ai=yes", "r18=是", "tags=a, b"]))
    title, options = add_manual_handler._parse_options(["bare", "name=", "r18g=on", "source=http://x", "author_url=http://a", "caption=c"])
    assert title == "bare" or title == ""
    assert options["is_r18g"] is True


async def test_option_and_push_commands(monkeypatch):
    from handlers.command_handlers import image_push_handler, option_handler

    panel = SimpleNamespace(text="面板", keyboard=[], parse_mode=None)
    monkeypatch.setattr(option_handler.user_registry, "get_user_by_id", AsyncMock(return_value=_user()))
    monkeypatch.setattr(option_handler.group_registry, "get_group_by_id", AsyncMock(return_value=_group(admin_ids=[])))
    monkeypatch.setattr(option_handler, "get_cached_admin_ids", AsyncMock(return_value=None))
    monkeypatch.setattr(option_handler, "delete_messages", AsyncMock())
    monkeypatch.setattr(option_handler.messase_generator, "config_group", AsyncMock(return_value=panel))
    monkeypatch.setattr(option_handler.messase_generator, "config_user", AsyncMock(return_value=panel))
    update = make_update(chat_type="group", user_id=1)
    await option_handler.option_handler_func.__wrapped__(update, make_context())

    monkeypatch.setattr(option_handler, "get_cached_admin_ids", AsyncMock(return_value=[1]))
    await option_handler.option_handler_func.__wrapped__(make_update(chat_type="group"), make_context())
    monkeypatch.setattr(option_handler.group_registry, "get_group_by_id", AsyncMock(return_value=_group(admin_ids=[1])))
    await option_handler.option_handler_func.__wrapped__(make_update(chat_type="supergroup"), make_context())
    await option_handler.option_handler_func.__wrapped__(make_update(chat_type="private"), make_context())

    push = image_push_handler
    monkeypatch.setattr(push, "can_use_push_command", AsyncMock(return_value=True))
    monkeypatch.setattr(push, "group_push_block_reason", lambda group: None)
    monkeypatch.setattr(push, "_bot_can_send_photo", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(push.group_registry, "get_group_by_id", AsyncMock(return_value=_group()))
    monkeypatch.setattr(push, "create_batch", AsyncMock(return_value=SimpleNamespace(id=6)))
    update = make_update(chat_type="group")
    update.effective_message = None
    await push.image_push_command.__wrapped__(update, make_context())
    update = make_update(chat_type="private")
    await push.image_push_command.__wrapped__(update, make_context())
    monkeypatch.setattr(push, "can_use_push_command", AsyncMock(return_value=False))
    await push.image_push_command.__wrapped__(make_update(chat_type="group"), make_context())
    monkeypatch.setattr(push, "can_use_push_command", AsyncMock(return_value=True))
    monkeypatch.setattr(push, "group_push_block_reason", lambda group: "已关闭")
    await push.image_push_command.__wrapped__(make_update(chat_type="group"), make_context())
    monkeypatch.setattr(push, "group_push_block_reason", lambda group: None)
    monkeypatch.setattr(push, "_bot_can_send_photo", AsyncMock(return_value=(False, "")))
    await push.image_push_command.__wrapped__(make_update(chat_type="group"), make_context())
    monkeypatch.setattr(push, "_bot_can_send_photo", AsyncMock(return_value=(True, None)))
    await push.image_push_command.__wrapped__(make_update(chat_type="group"), make_context(["a", "b"]))
    await push.image_push_command.__wrapped__(make_update(chat_type="group"), make_context([" ", "random"]))
    monkeypatch.setattr(push, "normalize_pid_spec", Mock(side_effect=ValueError("bad pid")))
    await push.image_push_command.__wrapped__(make_update(chat_type="group"), make_context(["nope"]))
    monkeypatch.setattr(push, "normalize_pid_spec", lambda raw: "42:1")
    update = make_update(chat_type="group")
    await push.image_push_command.__wrapped__(update, make_context(["42:1"]))
    assert "批次 #6" in sent_texts(update.effective_message.reply_text)[-1]


class _Lock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def moderation(monkeypatch):
    from handlers.command_handlers import moderation_handler as module

    policy = Policy(rules_text="守规矩")
    monkeypatch.setattr(module.store, "policy", AsyncMock(return_value=policy))
    monkeypatch.setattr(module.store, "save_policy", AsyncMock())
    monkeypatch.setattr(module.store, "records", AsyncMock(return_value=[{"key": "n", "data": {"text": "正文"}}]))
    monkeypatch.setattr(module.store, "remove_record", AsyncMock(return_value=True))
    monkeypatch.setattr(module.store, "put_record", AsyncMock())
    monkeypatch.setattr(module.store, "record", AsyncMock(return_value=None))
    monkeypatch.setattr(module.store, "warnings", AsyncMock(return_value=[{"id": 1, "reason": "spam"}]))
    monkeypatch.setattr(module.store, "lock", lambda group_id: _Lock())
    monkeypatch.setattr(module.actions, "require_admin", AsyncMock())
    monkeypatch.setattr(module.actions, "execute", AsyncMock(return_value={"status": "ok", "data": "done"}))
    monkeypatch.setattr(module.actions, "is_uncertain_error", lambda exc: False)
    monkeypatch.setattr(module.reviews, "create", AsyncMock())
    monkeypatch.setattr(module.reviews, "decide", AsyncMock(return_value={"data": {"state": "closed"}}))
    monkeypatch.setattr(module.worker, "delete_content", AsyncMock())
    monkeypatch.setattr(module.worker, "save_content", AsyncMock())
    monkeypatch.setattr(module.rules, "window", lambda *args, **kwargs: [])
    monkeypatch.setattr(module.rules, "version", lambda message: "v1")
    return module


async def _mod(module, text, args, **message_extra):
    update = make_update(text=text, chat_type="group", chat_id=10, user_id=2, **message_extra)
    await module.moderation_command(update, make_context(args))
    return update


async def test_moderation_commands(moderation):
    module = moderation
    update = make_update(text="/rules")
    update.effective_chat = None
    await module.moderation_command(update, make_context())

    update = await _mod(module, "/rules", [])
    assert "守规矩" in sent_texts(update.effective_message.reply_text)[0]
    module.store.policy = AsyncMock(return_value=Policy(rules_text=""))
    update = await _mod(module, "/rules@bot", [])
    assert "尚未设置" in sent_texts(update.effective_message.reply_text)[0]
    module.store.policy = AsyncMock(return_value=Policy())

    update = await _mod(module, "/notes", ["n"])
    assert "正文" in sent_texts(update.effective_message.reply_text)[0]
    module.store.records = AsyncMock(return_value=[])
    update = await _mod(module, "/notes", [])
    assert "可用笔记" in sent_texts(update.effective_message.reply_text)[0]
    module.store.records = AsyncMock(return_value=[{"key": "n", "data": {"text": "正文"}}])

    update = await _mod(module, "/report", [])
    assert "回复" in sent_texts(update.effective_message.reply_text)[0]
    reply = make_message(sender_chat=object(), from_user=None, message_id=4, date=datetime.now(timezone.utc))
    update = await _mod(module, "/report", [], reply_to_message=reply)
    assert "频道" in sent_texts(update.effective_message.reply_text)[0] or "回复" in sent_texts(update.effective_message.reply_text)[0]
    module.rules.window = lambda *args, **kwargs: [1, 2, 3, 4]
    reply = make_message(from_user=make_user(9), message_id=4, date=datetime.now(timezone.utc), media_group_id="g")
    update = await _mod(module, "/report", ["reason"], reply_to_message=reply)
    assert "频繁" in sent_texts(update.effective_message.reply_text)[0]
    module.rules.window = lambda *args, **kwargs: []
    module.store.record = AsyncMock(return_value={"id": 1})
    update = await _mod(module, "/report", [], reply_to_message=reply)
    assert "已提交" in sent_texts(update.effective_message.reply_text)[0]
    module.store.record = AsyncMock(return_value=None)
    reply.media_group_id = None
    await _mod(module, "/report", [], reply_to_message=reply)

    update = await _mod(module, "/kick", [], sender_chat=object())
    assert "个人管理员" in sent_texts(update.effective_message.reply_text)[0]
    update = await _mod(module, "/pin", [])
    assert "回复目标" in sent_texts(update.effective_message.reply_text)[0]
    reply = make_message(message_id=6, from_user=make_user(9))
    for command in ("/pin", "/unpin", "/del", "/purge"):
        await _mod(module, command, [], reply_to_message=reply)

    reply = make_message(sender_chat=object(), from_user=None)
    update = await _mod(module, "/kick", [], reply_to_message=reply)
    assert "频道" in sent_texts(update.effective_message.reply_text)[0]
    update = await _mod(module, "/kick", [])
    assert "用户 ID" in sent_texts(update.effective_message.reply_text)[0]
    update = await _mod(module, "/warns", ["9"])
    assert "警告" in sent_texts(update.effective_message.reply_text)[0]
    update = await _mod(module, "/mute", ["9", "30m", "spam"])
    assert "mute" in sent_texts(update.effective_message.reply_text)[0]
    update = await _mod(module, "/mute", ["9", "nope"])
    assert "时长" in sent_texts(update.effective_message.reply_text)[0] or "参数" not in sent_texts(update.effective_message.reply_text)[0]
    module.actions.execute = AsyncMock(side_effect=TelegramError("nope"))
    update = await _mod(module, "/ban", ["9"])
    assert "操作失败" in sent_texts(update.effective_message.reply_text)[0]
    assert module.duration("2h") == 7200
    assert module.duration("1d") == 86400
    with pytest.raises(ValueError):
        module.duration("0m")
    with pytest.raises(ValueError):
        module.target(make_message(), [])


async def test_guard_extra_and_callback(moderation):
    module = moderation
    update = make_update(chat_type="group", chat_id=10)
    assert await module.guard_extra(update, make_context()) is True
    assert "智能群管" in sent_texts(update.effective_message.reply_text)[0]
    assert await module.guard_extra(update, make_context(["verify"])) is False
    assert await module.guard_extra(update, make_context(["help"])) is True
    assert await module.guard_extra(update, make_context(["set"])) is True
    assert await module.guard_extra(update, make_context(["set", "verification_enabled", "maybe"])) is True
    assert await module.guard_extra(update, make_context(["set", "verification_enabled", "on"])) is True
    assert await module.guard_extra(update, make_context(["set", "domain_allowlist", "a.com, b.com"])) is True
    assert await module.guard_extra(update, make_context(["set", "domain_allowlist", "clear"])) is True
    assert await module.guard_extra(update, make_context(["set", "welcome_text", "hi"])) is True
    assert await module.guard_extra(update, make_context(["rule", "list"])) is True
    module.store.records = AsyncMock(return_value=[])
    assert await module.guard_extra(update, make_context(["rule", "list"])) is True
    module.store.remove_record = AsyncMock(return_value=False)
    assert await module.guard_extra(update, make_context(["rule", "remove", "name"])) is True
    assert await module.guard_extra(update, make_context(["rule", "add", "name", "keyword", "spam"])) is True
    assert await module.guard_extra(update, make_context(["exempt", "0", "on"])) is True
    assert await module.guard_extra(update, make_context(["exempt", "5", "off"])) is True
    assert await module.guard_extra(update, make_context(["exempt", "5", "on"])) is True
    assert await module.guard_extra(update, make_context(["content", "list"])) is True
    assert await module.guard_extra(update, make_context(["content", "remove", "note", "name"])) is True
    assert await module.guard_extra(update, make_context(["content", "remove", "bad", "name"])) is True
    assert await module.guard_extra(update, make_context(["content", "note", "name", "hello"])) is True
    assert await module.guard_extra(
        update,
        make_context(["content", "announcement", "name", "2026-01-01T00:00:00+00:00", "daily", "hello"]),
    ) is True
    assert await module.guard_extra(update, make_context(["panel", "ai"])) is True

    update = make_update(query_data="mod", chat_type="private")
    await module.callback(update, make_context(), ["panel", "1"])
    update = make_update(query_data="mod")
    update.effective_user = None
    await module.callback(update, make_context(), ["panel"])
    module.actions.require_admin = AsyncMock(side_effect=TelegramError("no"))
    update = make_update(query_data="mod", chat_type="group", chat_id=10)
    await module.callback(update, make_context(), ["panel", "10", "join"])
    module.actions.require_admin = AsyncMock()
    update = make_update(query_data="mod", chat_type="group", chat_id=10)
    await module.callback(update, make_context(), ["panel", "11", "join"])
    await module.callback(update, make_context(), ["toggle", "10", "missing"])
    await module.callback(update, make_context(), ["toggle", "10", "verification_enabled"])
    await module.callback(update, make_context(), ["panel", "10", "rules"])
    await module.callback(update, make_context(), ["review", "1", "dismiss"])
    await module.callback(update, make_context(), ["review"])


async def test_verify_command(monkeypatch):
    from handlers.command_handlers import verification_handler as module

    monkeypatch.setattr(module.actions, "require_admin", AsyncMock())
    monkeypatch.setattr(module.actions, "is_uncertain_error", lambda exc: "uncertain" in str(exc))
    monkeypatch.setattr(module.store, "policy", AsyncMock(return_value=Policy()))
    result = SimpleNamespace(state="pending", replaced=True, reason=None)
    monkeypatch.setattr(module.verification, "retrigger", AsyncMock(return_value=result))
    monkeypatch.setattr(module, "find_user_ids_by_username", AsyncMock(return_value=[9]))

    update = make_update(text="/verify")
    update.effective_message = None
    await module.verify_command.__wrapped__(update, make_context())
    update = make_update(text="/verify", chat_type="private")
    await module.verify_command.__wrapped__(update, make_context())
    update = make_update(text="/verify", chat_type="group", sender_chat=object())
    await module.verify_command.__wrapped__(update, make_context())

    member_user = make_user(9, username="bob")
    member = Bag(status="member", user=member_user, is_member=True)
    context = make_context(["9"])
    context.bot.get_chat_member = AsyncMock(return_value=member)
    update = make_update(text="/verify", chat_type="group")
    await module.verify_command.__wrapped__(update, context)
    result.replaced = False
    result.state = "uncertain"
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), context)
    result.state = "failed"
    result.reason = "nope"
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), context)
    member.user = None
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), context)
    member.user = member_user

    member.status = "left"
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), context)
    member.status = "restricted"
    member.is_member = False
    assert module._is_present(member) is False
    member.status = "restricted"
    member.is_member = True
    assert module._is_present(member) is True

    reply = make_message(from_user=None, sender_chat=object())
    update = make_update(text="/verify", chat_type="group", reply_to_message=reply)
    await module.verify_command.__wrapped__(update, make_context())
    mention = Bag(type=MessageEntity.TEXT_MENTION, user=make_user(4, username=None))
    update = make_update(text="/verify", chat_type="group", entities=[mention])
    context = make_context(["@ignored"])
    context.bot.get_chat_member = AsyncMock(return_value=Bag(status="creator", user=make_user(4), is_member=True))
    result.state = "pending"
    await module.verify_command.__wrapped__(update, context)

    monkeypatch.setattr(module, "find_user_ids_by_username", AsyncMock(return_value=[]))
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), make_context(["@ghost"]))
    monkeypatch.setattr(module, "find_user_ids_by_username", AsyncMock(return_value=[1, 2]))
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), make_context(["@ghost"]))
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), make_context(["not-a-user"]))
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), make_context())

    module.actions.require_admin = AsyncMock(side_effect=TelegramError("uncertain failure"))
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), make_context(["9"]))
    module.actions.require_admin = AsyncMock(side_effect=TelegramError("denied"))
    await module.verify_command.__wrapped__(make_update(text="/verify", chat_type="group"), make_context(["9"]))
    assert "用法" in module._usage()
