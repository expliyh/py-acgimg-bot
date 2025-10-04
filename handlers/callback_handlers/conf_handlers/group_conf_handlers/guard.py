"""Callback helpers for managing group guard settings via the config panel."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from registries import active_message_handler_registry
from services import group_guard

from .panel import refresh_group_config_panel

logger = logging.getLogger(__name__)

_TIMEOUT_STEP = 30


async def handle_guard_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    group_id: int,
    args: list[str],
    command_message_id: int | None,
) -> None:
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user

    if query is None or chat is None or user is None or not args:
        return

    action = args[0]
    panel_message_id = update.effective_message.message_id

    if action == "verify" and len(args) >= 2:
        await _toggle_verification(
            query_answer=query.answer,
            context=context,
            chat_id=chat.id,
            message_id=panel_message_id,
            group_id=group_id,
            command_message_id=command_message_id,
            enabled=args[1] == "on",
        )
        return

    if action == "kick" and len(args) >= 2:
        await _toggle_kick_mode(
            query_answer=query.answer,
            context=context,
            chat_id=chat.id,
            message_id=panel_message_id,
            group_id=group_id,
            command_message_id=command_message_id,
            enabled=args[1] == "on",
        )
        return

    if action == "filter" and len(args) >= 2:
        await _toggle_keyword_filter(
            query_answer=query.answer,
            context=context,
            chat_id=chat.id,
            message_id=panel_message_id,
            group_id=group_id,
            command_message_id=command_message_id,
            enabled=args[1] == "on",
        )
        return

    if action == "timeout" and len(args) >= 2:
        sub_action = args[1]
        if sub_action in {"inc", "dec"}:
            await _adjust_timeout(
                query_answer=query.answer,
                context=context,
                chat_id=chat.id,
                message_id=panel_message_id,
                group_id=group_id,
                command_message_id=command_message_id,
                increase=sub_action == "inc",
            )
            return
        if sub_action == "set":
            await _request_timeout_input(
                query_answer=query.answer,
                context=context,
                chat_id=chat.id,
                panel_message_id=panel_message_id,
                user_id=user.id,
                group_id=group_id,
            )
            return

    if action == "message" and len(args) >= 2 and args[1] == "set":
        await _request_message_input(
            query_answer=query.answer,
            context=context,
            chat_id=chat.id,
            panel_message_id=panel_message_id,
            user_id=user.id,
            group_id=group_id,
        )
        return

    if action == "keywords" and len(args) >= 2:
        await _handle_keyword_actions(
            update,
            context,
            group_id=group_id,
            args=args[1:],
            command_message_id=command_message_id,
            panel_message_id=panel_message_id,
        )
        return

    await query.answer()


async def _toggle_verification(
    *,
    query_answer,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    group_id: int,
    command_message_id: int | None,
    enabled: bool,
) -> None:
    updated = await group_guard.set_verification_enabled(group_id, enabled)
    await query_answer("进群验证已启用" if updated.verification_enabled else "进群验证已关闭")
    await refresh_group_config_panel(
        context,
        chat_id=chat_id,
        message_id=message_id,
        group_id=group_id,
        command_message_id=command_message_id,
    )


async def _toggle_kick_mode(
    *,
    query_answer,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    group_id: int,
    command_message_id: int | None,
    enabled: bool,
) -> None:
    updated = await group_guard.set_kick_on_timeout(group_id, enabled)
    await query_answer(
        "超时将踢出未验证成员" if updated.kick_on_timeout else "超时仅限制未验证成员"
    )
    await refresh_group_config_panel(
        context,
        chat_id=chat_id,
        message_id=message_id,
        group_id=group_id,
        command_message_id=command_message_id,
    )


async def _toggle_keyword_filter(
    *,
    query_answer,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    group_id: int,
    command_message_id: int | None,
    enabled: bool,
) -> None:
    updated = await group_guard.set_keyword_filter_enabled(group_id, enabled)
    await query_answer(
        "关键字过滤已启用" if updated.keyword_filter_enabled else "关键字过滤已关闭"
    )
    await refresh_group_config_panel(
        context,
        chat_id=chat_id,
        message_id=message_id,
        group_id=group_id,
        command_message_id=command_message_id,
    )


async def _adjust_timeout(
    *,
    query_answer,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    group_id: int,
    command_message_id: int | None,
    increase: bool,
) -> None:
    settings = await group_guard.get_guard_settings(group_id)
    delta = _TIMEOUT_STEP if increase else -_TIMEOUT_STEP
    target = settings.verification_timeout + delta
    updated = await group_guard.set_verification_timeout(group_id, target)
    await query_answer(f"验证超时已更新为 {updated.verification_timeout} 秒")
    await refresh_group_config_panel(
        context,
        chat_id=chat_id,
        message_id=message_id,
        group_id=group_id,
        command_message_id=command_message_id,
    )


async def _request_timeout_input(
    *,
    query_answer,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    panel_message_id: int,
    user_id: int,
    group_id: int,
) -> None:
    await active_message_handler_registry.set(
        user_id=user_id,
        group_id=group_id,
        handler_id=f"guard_set_timeout:{panel_message_id}",
    )
    await query_answer("请发送新的验证超时(15-3600秒)")
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "请发送新的验证超时秒数 (15-3600)。\n"
            "发送 - 或 取消 可退出并保持当前设置。"
        ),
    )


async def _request_message_input(
    *,
    query_answer,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    panel_message_id: int,
    user_id: int,
    group_id: int,
) -> None:
    await active_message_handler_registry.set(
        user_id=user_id,
        group_id=group_id,
        handler_id=f"guard_set_message:{panel_message_id}",
    )
    await query_answer("请发送新的验证提示")
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "请发送新的验证提示内容。\n"
            "发送 '-' 或 '默认' 可恢复系统默认提示。"
        ),
    )


async def _handle_keyword_actions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    group_id: int,
    args: list[str],
    command_message_id: int | None,
    panel_message_id: int,
) -> None:
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user

    if query is None or chat is None or user is None or not args:
        return

    action = args[0]

    if action == "list":
        await query.answer("关键字列表已发送")
        await _send_keyword_list(context, chat.id, group_id)
        return

    if action == "clear":
        removed = await group_guard.clear_keyword_rules(group_id)
        await query.answer(f"已清理 {removed} 条关键字")
        await refresh_group_config_panel(
            context,
            chat_id=chat.id,
            message_id=panel_message_id,
            group_id=group_id,
            command_message_id=command_message_id,
        )
        return

    if action == "add":
        await active_message_handler_registry.set(
            user_id=user.id,
            group_id=group_id,
            handler_id=f"guard_add_keyword:{panel_message_id}",
        )
        await query.answer("请发送要添加的关键字")
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "请发送要添加的关键字，支持可选参数 --regex 与 --case。\n"
                "示例: 违禁词 --regex \n若要取消，请发送 -。"
            ),
        )
        return

    if action == "remove":
        await active_message_handler_registry.set(
            user_id=user.id,
            group_id=group_id,
            handler_id=f"guard_remove_keyword:{panel_message_id}",
        )
        await query.answer("请发送要删除的规则 ID")
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "请发送需要删除的关键字规则 ID。\n"
                "可先使用“查看关键字”按钮确认编号，发送 - 可取消。"
            ),
        )
        return

    await query.answer()


async def _send_keyword_list(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    group_id: int,
) -> None:
    rules = await group_guard.list_keyword_rules(group_id)
    if not rules:
        text = "当前未配置关键字过滤规则。"
    else:
        lines = ["当前关键字规则:"]
        for rule in rules:
            flags: list[str] = []
            if rule.is_regex:
                flags.append("regex")
            if rule.case_sensitive:
                flags.append("case")
            suffix = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"#{rule.id}: {rule.pattern}{suffix}")
        lines.append("\n通过“添加关键字”按钮可继续添加新规则。")
        text = "\n".join(lines)

    await context.bot.send_message(chat_id=chat_id, text=text)
