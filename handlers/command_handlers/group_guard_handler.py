from __future__ import annotations

from typing import Sequence

from telegram import Update
from telegram.ext import ContextTypes

from handlers.registry import bot_handler
from registries import group_registry
from services import group_guard
from services.command_history import command_logger
from services.telegram_cache import get_cached_admin_ids
from utils import is_group_type


async def _ensure_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return False

    group = await group_registry.get_group_by_id(chat.id)
    admin_ids: set[int] = set(group.admin_ids or [])
    if not admin_ids:
        fetched = await get_cached_admin_ids(context, chat.id)
        if fetched:
            admin_ids.update(fetched)
    return bool(admin_ids and user.id in admin_ids)


def _format_settings_text(
    *,
    settings: group_guard.GuardSettings,
    keyword_rules: Sequence[group_guard.KeywordRule],
) -> str:
    verification_status = "已启用" if settings.verification_enabled else "已关闭"
    keyword_status = "已启用" if settings.keyword_filter_enabled else "已关闭"
    custom_message = settings.verification_message or "使用默认提示"
    return "\n".join(
        [
            "群管配置概览",
            "",
            f"进群验证: {verification_status}",
            f"验证超时: {settings.verification_timeout} 秒",
            f"失败处理: {'移出群组' if settings.kick_on_timeout else '仅限制发言'}",
            f"验证提示: {custom_message}",
            "",
            f"关键字过滤: {keyword_status}",
            f"关键字数量: {len(keyword_rules)}",
        ]
    )


async def _send_status(update: Update, settings: group_guard.GuardSettings) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    rules = await group_guard.list_keyword_rules(chat.id)
    text = _format_settings_text(settings=settings, keyword_rules=rules)
    await update.effective_message.reply_text(text)


def _normalize_bool(arg: str | None) -> bool | None:
    if arg is None:
        return None
    lowered = arg.lower()
    if lowered in {"on", "enable", "enabled", "true", "yes"}:
        return True
    if lowered in {"off", "disable", "disabled", "false", "no"}:
        return False
    return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@bot_handler(commands="guard")
@command_logger("guard")
async def group_guard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return

    if not is_group_type(chat.type):
        await message.reply_text("请在群组中使用此命令")
        return

    if not await _ensure_admin(update, context):
        await message.reply_text("只有群管理员可以配置群管功能")
        return

    args = context.args or []
    settings = await group_guard.get_guard_settings(chat.id)

    if not args:
        await _send_status(update, settings)
        await message.reply_text(
            "指令示例: /guard verify on | /guard keyword add 违禁词 --regex"
        )
        return

    section = args[0].lower()

    if section in {"status", "show"}:
        await _send_status(update, settings)
        return

    if section == "verify":
        await _handle_verify_command(update, context, settings)
        return

    if section in {"keyword", "keywords"}:
        await _handle_keyword_command(update, context)
        return

    await message.reply_text("未知的子命令，请使用 status / verify / keyword")


async def _handle_verify_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: group_guard.GuardSettings,
) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    args = context.args[1:]
    if not args:
        await _send_status(update, settings)
        return

    action = args[0].lower()

    if action in {"on", "off", "enable", "disable"}:
        desired = _normalize_bool(action)
        updated = await group_guard.set_verification_enabled(chat.id, bool(desired))
        await message.reply_text(
            f"进群验证已{'启用' if updated.verification_enabled else '关闭'}"
        )
        return

    if action == "timeout":
        timeout_value = _parse_int(args[1] if len(args) > 1 else None)
        if timeout_value is None:
            await message.reply_text("请提供有效的秒数，例如 /guard verify timeout 120")
            return
        updated = await group_guard.set_verification_timeout(chat.id, timeout_value)
        await message.reply_text(f"验证超时已更新为 {updated.verification_timeout} 秒")
        return

    if action == "message":
        if len(args) <= 1:
            await message.reply_text("请提供验证提示内容")
            return
        custom_message = " ".join(args[1:])
        updated = await group_guard.set_verification_message(chat.id, custom_message)
        summary = updated.verification_message or "使用默认提示"
        await message.reply_text(f"验证提示已更新: {summary}")
        return

    if action == "kick":
        desired = _normalize_bool(args[1] if len(args) > 1 else None)
        if desired is None:
            await message.reply_text("请使用 on/off 指定是否在超时时移出成员")
            return
        updated = await group_guard.set_kick_on_timeout(chat.id, desired)
        await message.reply_text(
            "超时处理已设置为移出群组" if updated.kick_on_timeout else "超时将仅限制发言"
        )
        return

    await message.reply_text("未知的 verify 子命令，可用: on/off, timeout, message, kick")


async def _handle_keyword_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    args = context.args[1:]
    if not args or args[0].lower() == "list":
        rules = await group_guard.list_keyword_rules(chat.id)
        if not rules:
            await message.reply_text("当前未配置关键字过滤规则")
            return
        lines = ["已配置的关键字规则:"]
        for rule in rules:
            flags = []
            if rule.is_regex:
                flags.append("regex")
            if rule.case_sensitive:
                flags.append("case")
            suffix = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"#{rule.id}: {rule.pattern}{suffix}")
        await message.reply_text("\n".join(lines))
        return

    action = args[0].lower()

    if action in {"on", "off", "enable", "disable"}:
        desired = _normalize_bool(action)
        updated = await group_guard.set_keyword_filter_enabled(chat.id, bool(desired))
        await message.reply_text(
            f"关键字过滤已{'启用' if updated.keyword_filter_enabled else '关闭'}"
        )
        return

    if action == "add":
        if len(args) <= 1:
            await message.reply_text("请提供需要拦截的关键字，例如 /guard keyword add 违禁词 --regex")
            return
        pattern_tokens = []
        is_regex = False
        case_sensitive = False
        for token in args[1:]:
            lowered = token.lower()
            if lowered in {"--regex", "--re"}:
                is_regex = True
                continue
            if lowered in {"--case", "--case-sensitive"}:
                case_sensitive = True
                continue
            pattern_tokens.append(token)
        pattern = " ".join(pattern_tokens).strip()
        if not pattern:
            await message.reply_text("关键字不能为空")
            return
        try:
            rule = await group_guard.add_keyword_rule(
                chat.id,
                pattern,
                is_regex=is_regex,
                case_sensitive=case_sensitive,
            )
        except ValueError as exc:
            await message.reply_text(str(exc))
            return
        flags = []
        if rule.is_regex:
            flags.append("regex")
        if rule.case_sensitive:
            flags.append("case")
        suffix = f" ({', '.join(flags)})" if flags else ""
        await message.reply_text(f"已添加规则 #{rule.id}: {rule.pattern}{suffix}")
        return

    if action == "remove":
        rule_id = _parse_int(args[1] if len(args) > 1 else None)
        if rule_id is None:
            await message.reply_text("请提供有效的规则 ID，例如 /guard keyword remove 3")
            return
        removed = await group_guard.remove_keyword_rule(chat.id, rule_id)
        if removed:
            await message.reply_text(f"规则 #{rule_id} 已删除")
        else:
            await message.reply_text("未找到指定规则")
        return

    if action == "clear":
        removed = await group_guard.clear_keyword_rules(chat.id)
        await message.reply_text(f"已清理 {removed} 条关键字规则")
        return

    await message.reply_text("未知的 keyword 子命令，可用: list, on/off, add, remove, clear")
