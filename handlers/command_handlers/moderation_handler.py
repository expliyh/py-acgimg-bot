"""Telegram commands and category panels for shared moderation services."""

import re
from datetime import datetime

from pydantic import ValidationError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from handlers.registry import bot_handler
from services.moderation import actions, reviews, rules, store, worker
from services.moderation.schemas import ActionRequest, Content, Rule

CATEGORIES = {
    "join": (
        "入群",
        [
            "verification_enabled",
            "verification_mode",
            "verification_timeout",
            "verification_message",
            "kick_on_timeout",
            "join_auto_approve",
            "join_requests_enabled",
            "raid_enabled",
            "raid_window",
            "raid_limit",
            "raid_duration",
        ],
    ),
    "rules": (
        "审核",
        [
            "keyword_filter_enabled",
            "rules_enabled",
            "domain_allowlist",
            "flood_enabled",
            "flood_window",
            "flood_limit",
            "repeat_window",
            "repeat_limit",
        ],
    ),
    "ai": (
        "AI",
        [
            "ai_spam",
            "ai_abuse",
            "ai_images",
            "ai_auto_threshold",
            "ai_review_threshold",
            "ai_daily_limit",
        ],
    ),
    "members": ("处罚", ["warning_limit", "warning_days", "mute_seconds"]),
    "content": (
        "群运营",
        [
            "welcome_enabled",
            "welcome_text",
            "goodbye_enabled",
            "goodbye_text",
            "rules_text",
            "replies_enabled",
            "clean_service_messages",
            "timezone",
            "log_days",
        ],
    ),
}


async def panel(message, group_id, category=None, *, edit=False):
    settings = (await store.policy(group_id)).model_dump()
    keyboard = [
        [
            InlineKeyboardButton(title, callback_data=f"mod:panel:{group_id}:{key}")
            for key, (title, _) in CATEGORIES.items()
        ]
    ]
    lines = [
        "智能群管",
        "配置：/guard set 字段 值",
        "规则：/guard rule add 名称 类型 内容",
        "群运营：/guard content 类型 名称 内容",
        "帮助：/guard help",
    ]
    if category in CATEGORIES:
        title, fields = CATEGORIES[category]
        lines = [f"群管 · {title}"]
        for field in fields:
            value = settings[field]
            lines.append(f"{field}: {value}")
            if isinstance(value, bool):
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{'关闭' if value else '启用'} {field}",
                            callback_data=f"mod:toggle:{group_id}:{field}",
                        )
                    ]
                )
        lines.append("修改数值/文本：/guard set 字段 值")
    method = message.edit_text if edit else message.reply_text
    await method("\n".join(lines)[:4000], reply_markup=InlineKeyboardMarkup(keyboard))


async def guard_extra(update, context):
    message, chat = update.effective_message, update.effective_chat
    args = context.args or []
    if not args or args[0] == "panel":
        await panel(message, chat.id, args[1] if len(args) > 1 else None)
        return True
    command = args[0]
    if command not in {"set", "rule", "content", "exempt", "help"}:
        return False
    try:
        if command == "help":
            await message.reply_text(
                "/guard set 字段 值（布尔值 on/off；白名单用逗号分隔）\n"
                "/guard rule add 名称 keyword|regex|link|invite|forward|media 内容\n"
                "/guard rule list | remove 名称\n"
                "/guard content note|reply 名称 内容\n"
                "/guard content announcement 名称 ISO时间 once|daily|weekly 内容\n"
                "/guard content list | remove 类型 名称\n"
                "/guard exempt 用户ID on|off\n"
                "/warn /warns /unwarn /mute /unmute /kick /ban /unban：回复消息或提供用户ID\n"
                "/mute 用户ID 30m 原因；时长支持 m/h/d\n"
                "/report 回复举报；/rules 群规；/notes 名称\n"
                "/pin /unpin /del 回复消息；/purge 回复起点消息（最多100条）\n"
                "日志和 AI 密钥通过 Web 管理台管理。"
            )
        elif command == "set":
            field, raw = args[1], " ".join(args[2:])
            current = (await store.policy(chat.id)).model_dump()
            if field not in current or not raw:
                raise ValueError("未知字段或缺少值")
            if isinstance(current[field], bool):
                if raw.lower() not in {"on", "off", "true", "false"}:
                    raise ValueError("请填写 on/off")
                value = raw.lower() in {"on", "true"}
            elif field == "domain_allowlist":
                value = (
                    [x.strip() for x in raw.split(",") if x.strip()]
                    if raw != "clear"
                    else []
                )
            else:
                value = raw
            await store.save_policy(chat.id, {field: value})
            await message.reply_text("配置已保存")
        elif command == "rule":
            if args[1] == "list":
                rows = await store.records(chat.id, "rule")
                await message.reply_text(
                    "\n".join(f"{r['key']}: {r['data']}" for r in rows)[:4000]
                    or "暂无规则"
                )
            elif args[1] == "remove":
                removed = await store.remove_record(chat.id, "rule", args[2])
                await message.reply_text("已删除" if removed else "规则不存在")
            else:
                rule = Rule(kind=args[3], pattern=" ".join(args[4:]))
                await store.put_record(chat.id, "rule", args[2], rule.model_dump())
                await message.reply_text(
                    "规则已保存；通过 /guard set rules_enabled on 启用审核"
                )
        elif command == "exempt":
            user_id = int(args[1])
            if user_id <= 0 or args[2] not in {"on", "off"}:
                raise ValueError("格式：/guard exempt 用户ID on|off")
            if args[2] == "on":
                await store.put_record(chat.id, "exempt", str(user_id), {})
            else:
                await store.remove_record(chat.id, "exempt", str(user_id))
            await message.reply_text("成员豁免已更新")
        else:
            if args[1] == "list":
                lines = []
                for kind in ("note", "reply", "announcement"):
                    lines.extend(
                        f"{kind}: {r['key']}"
                        for r in await store.records(chat.id, kind)
                    )
                await message.reply_text("\n".join(lines)[:4000] or "暂无内容")
            elif args[1] == "remove":
                if args[2] not in {"note", "reply", "announcement"}:
                    raise ValueError("无效内容类型")
                await store.remove_record(chat.id, args[2], args[3])
                await message.reply_text("已删除")
            else:
                extra = {}
                offset = 3
                if args[1] == "announcement":
                    extra = {
                        "due_at": datetime.fromisoformat(args[3]),
                        "repeat": args[4],
                        "timezone": (await store.policy(chat.id)).timezone,
                    }
                    offset = 5
                await worker.save_content(
                    chat.id,
                    Content(
                        kind=args[1],
                        name=args[2],
                        text=" ".join(args[offset:]),
                        **extra,
                    ),
                )
                await message.reply_text("内容已保存")
    except (ValueError, IndexError, ValidationError) as exc:
        await message.reply_text(
            f"参数错误：{str(exc)[:500]}\n使用 /guard help 查看格式"
        )
    return True


def target(message, args):
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.sender_chat or not reply.from_user:
            raise ValueError("不能将频道或匿名消息作为用户处罚对象")
        return reply.from_user.id, list(args)
    if not args or not args[0].isdigit():
        raise ValueError("请回复目标消息，或提供数字用户 ID")
    return int(args[0]), list(args[1:])


def duration(value):
    match = re.fullmatch(r"([1-9]\d*)([mhd])", value)
    if not match:
        raise ValueError("时长格式应为 30m、1h 或 7d")
    return int(match[1]) * {"m": 60, "h": 3600, "d": 86400}[match[2]]


@bot_handler(
    commands=[
        "warn",
        "warns",
        "unwarn",
        "mute",
        "unmute",
        "kick",
        "ban",
        "unban",
        "report",
        "rules",
        "notes",
        "pin",
        "unpin",
        "del",
        "purge",
    ]
)
async def moderation_command(update, context):
    message, chat, user = (
        update.effective_message,
        update.effective_chat,
        update.effective_user,
    )
    if not message or not chat or not user or chat.type not in {"group", "supergroup"}:
        return
    command = message.text.split()[0].split("@")[0][1:]
    args = context.args or []
    try:
        if command == "rules":
            await message.reply_text(
                (await store.policy(chat.id)).rules_text or "尚未设置群规"
            )
            return
        if command == "notes":
            rows = await store.records(chat.id, "note", enabled=True)
            text = next(
                (r["data"]["text"] for r in rows if args and r["key"] == args[0]), None
            )
            await message.reply_text(
                text or ("可用笔记：" + ", ".join(r["key"] for r in rows))[:4000]
            )
            return
        if command == "report":
            reply = message.reply_to_message
            if not reply or reply.sender_chat or not reply.from_user:
                raise ValueError("请回复需要举报的成员消息")
            if len(rules.window((chat.id, user.id, "report"), 60)) > 3:
                raise ValueError("举报过于频繁，请稍后再试")
            version = rules.version(reply)
            async with store.lock(chat.id):
                # Seed older, unobserved messages without overwriting a newer edit.
                if not await store.record(chat.id, "message", str(reply.message_id)):
                    await store.put_record(
                        chat.id,
                        "message",
                        str(reply.message_id),
                        {
                            "version": version,
                            "timestamp": (reply.edit_date or reply.date).timestamp(),
                            "blocked": False,
                        },
                    )
            await reviews.create(
                chat.id,
                f"report:{reply.message_id}",
                {
                    "kind": "message",
                    "user_id": reply.from_user.id,
                    "message_id": reply.message_id,
                    "version": version,
                    "incident": f"album:{reply.media_group_id}"
                    if reply.media_group_id
                    else f"message:{reply.message_id}",
                    "reason": " ".join(args)[:1000] or "成员举报",
                    "reporter": user.id,
                },
                context.bot,
            )
            await message.reply_text("已提交复核")
            return
        if message.sender_chat:
            raise ValueError("请使用个人管理员身份执行命令")
        await actions.require_admin(context.bot, chat.id, user.id)
        if command in {"pin", "unpin", "del", "purge"}:
            if not message.reply_to_message:
                raise ValueError("请回复目标消息")
            payload = {"message_id": message.reply_to_message.message_id}
            if command == "purge":
                payload["end_message_id"] = message.message_id
        else:
            user_id, rest = target(message, args)
            if command == "warns":
                warnings = await store.warnings(chat.id, user_id)
                await message.reply_text(
                    f"有效警告 {len(warnings)} 次\n"
                    + "\n".join(f"{r['id']}: {r['reason']}" for r in warnings)[:3500]
                )
                return
            payload = {"user_id": user_id}
            if command == "mute" and rest:
                payload["duration"] = duration(rest.pop(0))
            payload["reason"] = " ".join(rest) or "管理员操作"
        request = ActionRequest(
            action="delete" if command == "del" else command,
            request_id=f"tg:{update.update_id}",
            **payload,
        )
        result = await actions.execute(
            context.bot,
            chat.id,
            request,
            actor_id=user.id,
            source=f"telegram:{user.id}",
        )
        await message.reply_text(f"{command}: {result['status']}\n{result['data']}")
    except (ValueError, ValidationError, TelegramError) as exc:
        await message.reply_text(
            str(exc)[:1000]
            if isinstance(exc, ValueError)
            else f"操作失败：{type(exc).__name__}"
        )


async def callback(update, context, parts):
    query, chat, user = (
        update.callback_query,
        update.effective_chat,
        update.effective_user,
    )
    if not query or not chat or not user:
        return
    try:
        if chat.type not in {"group", "supergroup"}:
            raise ValueError("请在所属群内操作")
        await actions.require_admin(context.bot, chat.id, user.id)
        if parts[0] in {"panel", "toggle"}:
            if int(parts[1]) != chat.id:
                raise ValueError("面板不属于当前群")
            await query.answer()
            if parts[0] == "toggle":
                field = parts[2]
                settings = (await store.policy(chat.id)).model_dump()
                if field not in settings or not isinstance(settings[field], bool):
                    raise ValueError("无效开关")
                await store.save_policy(chat.id, {field: not settings[field]})
                category = next(
                    key for key, (_, fields) in CATEGORIES.items() if field in fields
                )
            else:
                category = parts[2]
            await panel(query.message, chat.id, category, edit=True)
        elif parts[0] == "review":
            await query.answer()
            result = await reviews.decide(
                context.bot,
                chat.id,
                parts[1],
                parts[2],
                "管理员复核",
                actor_id=user.id,
                source=f"telegram:{user.id}",
            )
            await query.edit_message_text(f"复核结果：{result['data']['state']}")
    except (ValueError, IndexError, TelegramError) as exc:
        await query.answer(
            str(exc)[:150] if isinstance(exc, ValueError) else "操作失败",
            show_alert=True,
        )
