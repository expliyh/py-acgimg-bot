"""Administrator command for manually restarting member verification."""

from __future__ import annotations

from telegram import MessageEntity, Update, User
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from handlers.registry import bot_handler
from registries.user_registry import find_user_ids_by_username
from services.command_history import command_logger
from services.moderation import actions, store, verification


def _usage() -> str:
    return "用法：/verify @username、/verify 用户ID，或回复目标用户消息后发送 /verify"


async def _resolve_target(message, args: list[str]) -> tuple[int, User | None]:
    reply = message.reply_to_message
    if reply is not None:
        if reply.sender_chat or reply.from_user is None:
            raise ValueError("不能将频道或匿名消息作为验证目标")
        return reply.from_user.id, reply.from_user

    if len(args) != 1:
        raise ValueError(_usage())

    text_mention = next(
        (
            entity.user
            for entity in (message.entities or ())
            if entity.type == MessageEntity.TEXT_MENTION and entity.user is not None
        ),
        None,
    )
    if text_mention is not None:
        return text_mention.id, text_mention

    value = args[0].strip()
    if value.isdigit():
        return int(value), None
    if not value.startswith("@") or len(value) == 1:
        raise ValueError("目标必须是 @username、文本提及、数字用户 ID，或回复目标消息")

    matches = await find_user_ids_by_username(value)
    if not matches:
        raise ValueError(
            "未找到该 username；请先让机器人见过该用户，或改用文本提及/数字用户 ID"
        )
    if len(matches) > 1:
        raise ValueError("该 username 存在多个历史匹配，请改用数字用户 ID")
    return matches[0], None


def _is_present(member) -> bool:
    if member.status in {"left", "kicked"}:
        return False
    if member.status == "restricted" and not getattr(member, "is_member", False):
        return False
    return True


@bot_handler(commands="verify")
@command_logger("verify")
async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    actor = update.effective_user
    if message is None or chat is None or actor is None:
        return
    if chat.type not in {"group", "supergroup"}:
        await message.reply_text("请在群组中使用此命令")
        return
    if message.sender_chat:
        await message.reply_text("请使用个人管理员身份执行命令")
        return

    try:
        await actions.require_admin(context.bot, chat.id, actor.id)
        target_id, referenced_user = await _resolve_target(
            message, list(context.args or [])
        )
        member = await context.bot.get_chat_member(chat.id, target_id)
        if not _is_present(member):
            raise ValueError("目标用户当前不在本群")
        target_user = referenced_user or member.user
        if target_user is None:
            raise ValueError("无法读取目标用户信息")
        settings = await store.policy(chat.id)
        result = await verification.retrigger(
            context.bot,
            chat.id,
            target_user,
            chat.title or str(chat.id),
            settings,
            actor_id=actor.id,
            request_id=str(update.update_id),
        )
        if result.state == "pending":
            action = "替换旧验证并重新发起" if result.replaced else "重新发起"
            label = f"@{target_user.username}" if target_user.username else str(target_id)
            await message.reply_text(f"已为 {label} {action}入群验证")
        elif result.state == "uncertain":
            await message.reply_text("验证操作结果不确定，请检查机器人权限和目标成员状态后再处理")
        else:
            await message.reply_text(f"重新触发失败：{result.reason or result.state}")
    except ValueError as exc:
        await message.reply_text(str(exc)[:1000])
    except TelegramError as exc:
        if actions.is_uncertain_error(exc):
            await message.reply_text("Telegram 操作结果不确定，请稍后检查验证状态")
        else:
            await message.reply_text(f"操作失败：{type(exc).__name__}")
