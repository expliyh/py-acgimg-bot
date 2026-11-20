"""Guard command, callback, and follow-up message flows with Telegram mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from telegram.error import TelegramError

from services.group_guard import GuardSettings, KeywordRule
from services.moderation.schemas import Policy
from tests.unit.telegram_fakes import make_context, make_update, sent_texts


def _settings(**overrides) -> GuardSettings:
    data = dict(
        group_id=10,
        verification_enabled=True,
        verification_timeout=90,
        verification_message="请点按钮",
        keyword_filter_enabled=True,
        kick_on_timeout=False,
    )
    data.update(overrides)
    return GuardSettings(**data)


def _rule(**overrides) -> KeywordRule:
    data = dict(id=3, pattern="违禁词", is_regex=False, case_sensitive=False)
    data.update(overrides)
    return KeywordRule(**data)


@pytest.fixture
def guard_cmd(monkeypatch):
    from handlers.command_handlers import group_guard_handler as module

    settings = _settings()
    service = module.group_guard
    monkeypatch.setattr(service, "get_guard_settings", AsyncMock(return_value=settings))
    monkeypatch.setattr(service, "list_keyword_rules", AsyncMock(return_value=[_rule(), _rule(id=4, pattern="a+b", is_regex=True, case_sensitive=True)]))
    monkeypatch.setattr(service, "set_verification_enabled", AsyncMock(return_value=settings))
    monkeypatch.setattr(service, "set_verification_timeout", AsyncMock(return_value=settings))
    monkeypatch.setattr(service, "set_verification_message", AsyncMock(return_value=settings))
    monkeypatch.setattr(service, "set_kick_on_timeout", AsyncMock(return_value=_settings(kick_on_timeout=True)))
    monkeypatch.setattr(service, "set_keyword_filter_enabled", AsyncMock(return_value=settings))
    monkeypatch.setattr(service, "add_keyword_rule", AsyncMock(return_value=_rule(is_regex=True, case_sensitive=True)))
    monkeypatch.setattr(service, "remove_keyword_rule", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "clear_keyword_rules", AsyncMock(return_value=2))
    monkeypatch.setattr(module, "is_admin", AsyncMock(return_value=True))
    return module


async def _run(module, update, args):
    await module.group_guard_command.__wrapped__(update, make_context(args))


async def test_guard_ignores_update_without_message(guard_cmd):
    update = make_update(chat_type="group")
    update.effective_message = None
    await _run(guard_cmd, update, [])


async def test_guard_rejects_private_chat(guard_cmd):
    update = make_update(chat_type="private")
    await _run(guard_cmd, update, [])
    assert "群组" in sent_texts(update.effective_message.reply_text)[0]


@pytest.mark.parametrize("admin", [False])
async def test_guard_rejects_non_admin(guard_cmd, monkeypatch, admin):
    monkeypatch.setattr(guard_cmd, "is_admin", AsyncMock(return_value=admin))
    update = make_update(chat_type="supergroup")
    await _run(guard_cmd, update, ["status"])
    assert "管理员" in sent_texts(update.effective_message.reply_text)[0]


async def test_guard_rejects_sender_chat_and_telegram_errors(guard_cmd, monkeypatch):
    update = make_update(chat_type="group", sender_chat=object())
    await _run(guard_cmd, update, ["status"])
    assert "管理员" in sent_texts(update.effective_message.reply_text)[0]

    monkeypatch.setattr(guard_cmd, "is_admin", AsyncMock(side_effect=TelegramError("boom")))
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["status"])
    assert "管理员" in sent_texts(update.effective_message.reply_text)[0]


async def test_guard_missing_chat_in_admin_check(guard_cmd):
    update = make_update(chat_type="group")
    update.effective_chat = None
    assert await guard_cmd._ensure_admin(update, make_context()) is False


async def test_guard_status_and_empty_args_use_policy(guard_cmd):
    update = make_update(chat_type="group", chat_id=10)
    await _run(guard_cmd, update, [])
    texts = sent_texts(update.effective_message.reply_text)
    assert any("智能群管" in text for text in texts)

    update = make_update(chat_type="group", chat_id=10)
    await _run(guard_cmd, update, ["status"])
    overview = sent_texts(update.effective_message.reply_text)[0]
    assert "进群验证" in overview
    assert "机器人入群审批" in overview

    update = make_update(chat_type="group", chat_id=10)
    await _run(guard_cmd, update, ["show"])
    assert "关键字" in sent_texts(update.effective_message.reply_text)[0]


async def test_guard_status_without_chat_returns(guard_cmd):
    update = make_update(chat_type="group")
    update.effective_chat = None
    await guard_cmd._send_status(update, _settings())


async def test_guard_unknown_section(guard_cmd):
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["nope"])
    assert "未知的子命令" in sent_texts(update.effective_message.reply_text)[0]


async def test_guard_verify_branches(guard_cmd, monkeypatch):
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify"])
    assert "进群验证" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "off"])
    assert "进群验证已" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "timeout"])
    assert "有效的秒数" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "timeout", "abc"])
    assert "有效的秒数" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "timeout", "120"])
    assert "120" in sent_texts(update.effective_message.reply_text)[0] or "90" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "message"])
    assert "验证提示内容" in sent_texts(update.effective_message.reply_text)[0]

    monkeypatch.setattr(
        guard_cmd.group_guard,
        "set_verification_message",
        AsyncMock(side_effect=ValueError("太长")),
    )
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "message", "hello"])
    assert sent_texts(update.effective_message.reply_text) == ["太长"]

    monkeypatch.setattr(
        guard_cmd.group_guard,
        "set_verification_message",
        AsyncMock(return_value=_settings(verification_message=None)),
    )
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "message", "新提示"])
    assert "默认提示" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "kick"])
    assert "on/off" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "kick", "on"])
    assert "移出群组" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["verify", "wat"])
    assert "未知的 verify" in sent_texts(update.effective_message.reply_text)[0]


async def test_guard_verify_without_message_returns(guard_cmd):
    update = make_update(chat_type="group")
    update.effective_message = None
    await guard_cmd._handle_verify_command(update, make_context(["verify"]), _settings())


async def test_guard_keyword_branches(guard_cmd, monkeypatch):
    monkeypatch.setattr(guard_cmd.group_guard, "list_keyword_rules", AsyncMock(return_value=[]))
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "list"])
    assert "未配置" in sent_texts(update.effective_message.reply_text)[0]

    monkeypatch.setattr(
        guard_cmd.group_guard,
        "list_keyword_rules",
        AsyncMock(return_value=[_rule(), _rule(id=8, pattern="ab", is_regex=True)]),
    )
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keywords"])
    text = sent_texts(update.effective_message.reply_text)[0]
    assert "#3" in text and "regex" in text

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "disable"])
    assert "关键字过滤已" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "add"])
    assert "请提供" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "add", "--regex", "--case"])
    assert "不能为空" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "add", "违禁", "--re", "--case-sensitive"])
    assert "已添加" in sent_texts(update.effective_message.reply_text)[0]

    monkeypatch.setattr(
        guard_cmd.group_guard,
        "add_keyword_rule",
        AsyncMock(side_effect=ValueError("正则无效")),
    )
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "add", "("])
    assert sent_texts(update.effective_message.reply_text) == ["正则无效"]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "remove"])
    assert "规则 ID" in sent_texts(update.effective_message.reply_text)[0]

    monkeypatch.setattr(guard_cmd.group_guard, "remove_keyword_rule", AsyncMock(return_value=False))
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "remove", "9"])
    assert "未找到" in sent_texts(update.effective_message.reply_text)[0]

    monkeypatch.setattr(guard_cmd.group_guard, "remove_keyword_rule", AsyncMock(return_value=True))
    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "remove", "3"])
    assert "已删除" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "clear"])
    assert "2" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(chat_type="group")
    await _run(guard_cmd, update, ["keyword", "wat"])
    assert "未知的 keyword" in sent_texts(update.effective_message.reply_text)[0]


async def test_guard_keyword_without_message_returns(guard_cmd):
    update = make_update(chat_type="group")
    update.effective_chat = None
    await guard_cmd._handle_keyword_command(update, make_context(["keyword", "list"]))


def test_guard_bool_and_int_parsers(guard_cmd):
    assert guard_cmd._normalize_bool(None) is None
    assert guard_cmd._normalize_bool("YES") is True
    assert guard_cmd._normalize_bool("disabled") is False
    assert guard_cmd._normalize_bool("maybe") is None
    assert guard_cmd._parse_int(None) is None
    assert guard_cmd._parse_int("12") == 12
    assert guard_cmd._parse_int("x") is None
    assert guard_cmd._parse_int(object()) is None


async def test_format_settings_uses_default_prompt(guard_cmd):
    text = guard_cmd._format_settings_text(settings=_settings(verification_message=None, verification_enabled=False, keyword_filter_enabled=False), keyword_rules=[])
    assert "使用默认提示" in text
    assert "已关闭" in text


@pytest.fixture
def guard_cb(monkeypatch):
    from handlers.callback_handlers.conf_handlers.group_conf_handlers import guard as module

    monkeypatch.setattr(module, "refresh_group_config_panel", AsyncMock())
    monkeypatch.setattr(module.group_guard, "set_verification_enabled", AsyncMock(return_value=_settings()))
    monkeypatch.setattr(module.group_guard, "set_kick_on_timeout", AsyncMock(return_value=_settings(kick_on_timeout=True)))
    monkeypatch.setattr(module.group_guard, "set_keyword_filter_enabled", AsyncMock(return_value=_settings(keyword_filter_enabled=False)))
    monkeypatch.setattr(module.group_guard, "get_guard_settings", AsyncMock(return_value=_settings(verification_timeout=60)))
    monkeypatch.setattr(module.group_guard, "set_verification_timeout", AsyncMock(return_value=_settings(verification_timeout=90)))
    monkeypatch.setattr(module.group_guard, "clear_keyword_rules", AsyncMock(return_value=1))
    monkeypatch.setattr(module.group_guard, "list_keyword_rules", AsyncMock(return_value=[_rule(is_regex=True, case_sensitive=True)]))
    monkeypatch.setattr(module.active_message_handler_registry, "set", AsyncMock())
    return module


async def _guard_action(module, args):
    update = make_update(chat_type="group", chat_id=10, user_id=2, query_data="conf:group:guard")
    context = make_context()
    await module.handle_guard_action(
        update,
        context,
        group_id=10,
        args=args,
        command_message_id=4,
    )
    return update, context


async def test_guard_callback_early_returns(guard_cb):
    update = make_update(query_data="x")
    update.callback_query = None
    await guard_cb.handle_guard_action(update, make_context(), group_id=1, args=["verify", "on"], command_message_id=None)
    update = make_update(query_data="x")
    await guard_cb.handle_guard_action(update, make_context(), group_id=1, args=[], command_message_id=None)


async def test_guard_callback_toggles_and_inputs(guard_cb):
    update, _context = await _guard_action(guard_cb, ["verify", "on"])
    update.callback_query.answer.assert_awaited()
    update, _context = await _guard_action(guard_cb, ["kick", "off"])
    assert "踢出" in update.callback_query.answer.await_args.args[0] or "限制" in update.callback_query.answer.await_args.args[0]
    await _guard_action(guard_cb, ["filter", "off"])
    await _guard_action(guard_cb, ["timeout", "inc"])
    await _guard_action(guard_cb, ["timeout", "dec"])
    update, context = await _guard_action(guard_cb, ["timeout", "set"])
    context.bot.send_message.assert_awaited()
    update, context = await _guard_action(guard_cb, ["message", "set"])
    assert any("验证提示" in text for text in sent_texts(context.bot.send_message))
    await _guard_action(guard_cb, ["timeout", "nope"])
    update, _context = await _guard_action(guard_cb, ["unknown"])
    update.callback_query.answer.assert_awaited()


async def test_guard_callback_keywords(guard_cb):
    update, context = await _guard_action(guard_cb, ["keywords", "list"])
    assert any("当前关键字" in text for text in sent_texts(context.bot.send_message))
    guard_cb.group_guard.list_keyword_rules = AsyncMock(return_value=[])
    _update, context = await _guard_action(guard_cb, ["keywords", "list"])
    assert any("未配置" in text for text in sent_texts(context.bot.send_message))
    await _guard_action(guard_cb, ["keywords", "clear"])
    await _guard_action(guard_cb, ["keywords", "add"])
    await _guard_action(guard_cb, ["keywords", "remove"])
    update, _context = await _guard_action(guard_cb, ["keywords", "nope"])
    update.callback_query.answer.assert_awaited()

    bare = make_update(query_data="x")
    bare.effective_user = None
    await guard_cb._handle_keyword_actions(
        bare,
        make_context(),
        group_id=1,
        args=["list"],
        command_message_id=None,
        panel_message_id=1,
    )


async def test_group_conf_dispatch(monkeypatch):
    from handlers.callback_handlers.conf_handlers.group_conf_handlers import group_conf_handler as module
    from telegram.error import TelegramError as TgError

    refresh = AsyncMock()
    monkeypatch.setattr(module, "refresh_group_config_panel", refresh)
    close = AsyncMock()
    monkeypatch.setattr(module, "close_panel", close)
    handler = AsyncMock()
    monkeypatch.setitem(module._HANDLER_MAP, "enable", handler)
    monkeypatch.setattr("services.moderation.actions.is_admin", AsyncMock(return_value=True))

    update = make_update(chat_type="group", chat_id=8, user_id=3, query_data="x")
    await module.group_conf_handler_func(update, make_context(), [])
    update.callback_query = None
    await module.group_conf_handler_func(update, make_context(), ["8"])

    update = make_update(chat_type="group", chat_id=8, query_data="x")
    update.effective_chat = None
    await module.group_conf_handler_func(update, make_context(), ["8"])

    update = make_update(chat_type="group", chat_id=8, query_data="x")
    await module.group_conf_handler_func(update, make_context(), ["nope"])
    assert update.callback_query.answer.await_args.kwargs["show_alert"] is True

    update = make_update(chat_type="group", chat_id=8, query_data="x")
    await module.group_conf_handler_func(update, make_context(), ["9", "enable", "on", "1"])
    assert "无效的群组" in update.callback_query.answer.await_args.args[0]

    update = make_update(chat_type="group", chat_id=8, query_data="x")
    update.effective_user = None
    await module.group_conf_handler_func(update, make_context(), ["8"])

    monkeypatch.setattr("services.moderation.actions.is_admin", AsyncMock(side_effect=TgError("no")))
    update = make_update(chat_type="group", chat_id=8, query_data="x")
    await module.group_conf_handler_func(update, make_context(), ["8", "enable", "on"])
    assert "管理员" in update.callback_query.answer.await_args.args[0]

    monkeypatch.setattr("services.moderation.actions.is_admin", AsyncMock(return_value=True))
    update = make_update(chat_type="group", chat_id=8, query_data="x")
    await module.group_conf_handler_func(update, make_context(), ["8"])
    update.callback_query.answer.assert_awaited()

    context = make_context()
    update = make_update(chat_type="group", chat_id=8, query_data="x")
    await module.group_conf_handler_func(update, context, ["8", "panel", "refresh", "15"])
    refresh.assert_awaited()
    update = make_update(chat_type="group", chat_id=8, query_data="x")
    await module.group_conf_handler_func(update, context, ["8", "panel", "close", "bad"])
    close.assert_awaited()
    update = make_update(chat_type="group", chat_id=8, query_data="x")
    await module.group_conf_handler_func(update, context, ["8", "missing", "on", "3"])
    update = make_update(chat_type="group", chat_id=8, query_data="x")
    await module.group_conf_handler_func(update, context, ["8", "enable", "on", "3"])
    handler.assert_awaited()
    assert module._parse_command_message_id([]) is None
    assert module._extract_args(["8", "enable"]) == (None, [])
    assert module._extract_args(["8", "enable", "on"]) == (None, ["on"])


async def test_group_toggle_handlers(monkeypatch):
    from handlers.callback_handlers.conf_handlers.group_conf_handlers import enable, r18, setu, chat_placeholder

    for module, method in (
        (enable, "set_group_enable"),
        (r18, "set_group_sanity_limit"),
        (setu, "set_group_allow_setu"),
    ):
        monkeypatch.setattr(module, "refresh_group_config_panel", AsyncMock())
        monkeypatch.setattr(module.group_registry, method, AsyncMock())
        update = make_update(chat_type="group", query_data="x")
        handler = {
            enable: enable.handle_enable_toggle,
            r18: r18.handle_r18_toggle,
            setu: setu.handle_setu_toggle,
        }[module]
        await handler(update, make_context(), group_id=1, args=[], command_message_id=1)
        await handler(update, make_context(), group_id=1, args=["maybe"], command_message_id=1)
        await handler(update, make_context(), group_id=1, args=["on"], command_message_id=2)
        await handler(update, make_context(), group_id=1, args=["off"], command_message_id=None)
        update.callback_query = None
        await handler(update, make_context(), group_id=1, args=["on"], command_message_id=None)

    update = make_update(query_data="x")
    await chat_placeholder.handle_chat_placeholder(update, make_context(), group_id=1, args=[], command_message_id=None)
    assert "暂未实现" in update.callback_query.answer.await_args.args[0]
    update.callback_query = None
    await chat_placeholder.handle_chat_placeholder(update, make_context(), group_id=1, args=[], command_message_id=None)


def _pending(prefix, metadata="20"):
    async def getter(user_id, group_id=0):
        return f"{prefix}:{metadata}"

    return getter


@pytest.fixture
def pending(monkeypatch):
    modules = {}
    names = [
        "guard_add_keyword",
        "guard_remove_keyword",
        "guard_set_message",
        "guard_set_timeout",
    ]
    for name in names:
        module = __import__(f"handlers.message_handlers.{name}", fromlist=[name])
        monkeypatch.setattr(module, "refresh_group_config_panel", AsyncMock())
        monkeypatch.setattr(module.active_message_handler_registry, "delete", AsyncMock())
        monkeypatch.setattr("services.moderation.actions.is_admin", AsyncMock(return_value=True))
        modules[name] = module
    return modules


async def test_pending_guard_messages_cover_branches(pending, monkeypatch):
    add = pending["guard_add_keyword"]
    remove = pending["guard_remove_keyword"]
    message = pending["guard_set_message"]
    timeout = pending["guard_set_timeout"]
    monkeypatch.setattr(add.group_guard, "add_keyword_rule", AsyncMock(return_value=_rule(is_regex=True, case_sensitive=True)))
    monkeypatch.setattr(remove.group_guard, "remove_keyword_rule", AsyncMock(return_value=True))
    monkeypatch.setattr(message.group_guard, "set_verification_message", AsyncMock(return_value=_settings()))
    monkeypatch.setattr(timeout.group_guard, "set_verification_timeout", AsyncMock(return_value=_settings(verification_timeout=30)))

    async def run(module, func_name, text, key):
        monkeypatch.setattr(module.active_message_handler_registry, "get", AsyncMock(return_value=key))
        update = make_update(text=text, chat_type="group", chat_id=10, user_id=2)
        context = make_context()
        await getattr(module, func_name)(update, context)
        return update, context

    update, _context = await run(add, "guard_add_keyword", None, "guard_add_keyword:20")
    update.effective_message = None
    await add.guard_add_keyword(update, make_context())

    monkeypatch.setattr(add.active_message_handler_registry, "get", AsyncMock(return_value=None))
    await add.guard_add_keyword(make_update(text="x", chat_type="group"), make_context())

    monkeypatch.setattr("services.moderation.actions.is_admin", AsyncMock(return_value=False))
    update, _context = await run(add, "guard_add_keyword", "spam", "guard_add_keyword:20")
    assert "失效" in sent_texts(update.effective_message.reply_text)[0]

    update = make_update(text="spam", chat_type="group", sender_chat=object())
    monkeypatch.setattr(add.active_message_handler_registry, "get", AsyncMock(return_value="guard_add_keyword:20"))
    await add.guard_add_keyword(update, make_context())

    monkeypatch.setattr("services.moderation.actions.is_admin", AsyncMock(side_effect=TelegramError("x")))
    await run(remove, "guard_remove_keyword", "1", "guard_remove_keyword:20")

    monkeypatch.setattr("services.moderation.actions.is_admin", AsyncMock(return_value=True))
    await run(add, "guard_add_keyword", "spam", "guard_add_keyword:bad")
    context = make_context()
    context.bot.delete_message = AsyncMock(side_effect=TelegramError("gone"))
    monkeypatch.setattr(add.active_message_handler_registry, "get", AsyncMock(return_value="guard_add_keyword:20"))
    await add.guard_add_keyword(make_update(text="-", chat_type="group"), context)
    await run(add, "guard_add_keyword", "--regex", "guard_add_keyword:20")
    monkeypatch.setattr(add.group_guard, "add_keyword_rule", AsyncMock(side_effect=ValueError("bad")))
    await run(add, "guard_add_keyword", "word --regex --case", "guard_add_keyword:20")
    monkeypatch.setattr(add.group_guard, "add_keyword_rule", AsyncMock(return_value=_rule()))
    _update, context = await run(add, "guard_add_keyword", "word", "guard_add_keyword:20")
    assert any("已添加" in text for text in sent_texts(context.bot.send_message))

    await run(remove, "guard_remove_keyword", "取消", "guard_remove_keyword:20")
    await run(remove, "guard_remove_keyword", "abc", "guard_remove_keyword:bad")
    await run(remove, "guard_remove_keyword", "nope", "guard_remove_keyword:20")
    monkeypatch.setattr(remove.group_guard, "remove_keyword_rule", AsyncMock(return_value=False))
    await run(remove, "guard_remove_keyword", "4", "guard_remove_keyword:20")
    monkeypatch.setattr(remove.group_guard, "remove_keyword_rule", AsyncMock(return_value=True))
    _update, context = await run(remove, "guard_remove_keyword", "4", "guard_remove_keyword:20")
    assert any("已删除" in text for text in sent_texts(context.bot.send_message))

    await run(message, "guard_set_message", "默认", "guard_set_message:20")
    await run(message, "guard_set_message", "x" * 401, "guard_set_message:20")
    await run(message, "guard_set_message", "bad", "guard_set_message:nope")
    monkeypatch.setattr(message.group_guard, "set_verification_message", AsyncMock(return_value=_settings(verification_message=None)))
    await run(message, "guard_set_message", "新提示", "guard_set_message:20")

    await run(timeout, "guard_set_timeout", "cancel", "guard_set_timeout:20")
    await run(timeout, "guard_set_timeout", "abc", "guard_set_timeout:20")
    await run(timeout, "guard_set_timeout", "1", "guard_set_timeout:20")
    await run(timeout, "guard_set_timeout", "4000", "guard_set_timeout:bad")
    _update, context = await run(timeout, "guard_set_timeout", "30", "guard_set_timeout:20")
    assert any("30" in text for text in sent_texts(context.bot.send_message))


async def test_policy_object_is_real_for_status_text():
    dumped = Policy().model_dump()
    assert "bot_join_approval_enabled" in dumped
