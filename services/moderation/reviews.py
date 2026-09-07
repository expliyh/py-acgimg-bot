from datetime import timedelta

from sqlalchemy import update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from models import GuardRecord
from registries import engine

from . import actions, store


async def create(group_id, key, data, bot=None):
    async with store.lock(group_id):
        existing = await store.record(group_id, "review", key)
        if existing:
            return existing
        row = await store.put_record(
            group_id, "review", key, data | {"state": "pending"}
        )
    if bot:
        buttons = (
            [("批准", "approve_join"), ("拒绝", "reject_join")]
            if data.get("kind") == "join"
            else [("处罚", "punish"), ("忽略", "dismiss")]
        )
        try:
            sent = await bot.send_message(
                group_id,
                f"待管理员复核 #{row['id'][:8]}\n{data.get('reason', '成员举报')[:1000]}",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                label, callback_data=f"mod:review:{row['id']}:{action}"
                            )
                            for label, action in buttons
                        ]
                    ]
                ),
            )
            await store.task(
                group_id,
                "delete",
                store.now() + timedelta(hours=24),
                {"message_id": sent.message_id},
            )
        except TelegramError:
            pass  # The Web review remains available.
    return row


async def decide(
    bot,
    group_id,
    review_id,
    decision,
    reason,
    actor_id=None,
    source="web:deployment-admin",
):
    await actions.require_admin(bot, group_id, actor_id)
    async with engine.new_session() as session:
        row = await session.get(GuardRecord, review_id)
        if not row or row.group_id != group_id or row.kind != "review":
            raise ValueError("复核记录不存在")
        data, key = dict(row.data), row.key
        if data["state"] != "pending":
            raise ValueError("该记录已处理或正在处理")
        if (data.get("kind") == "join") != (
            decision in {"approve_join", "reject_join"}
        ) and decision not in {"dismiss"}:
            raise ValueError("操作与复核类型不匹配")
        changed = await session.execute(
            update(GuardRecord)
            .where(GuardRecord.id == review_id, GuardRecord.data == row.data)
            .values(data=data | {"state": "processing"})
        )
        await session.commit()
        if not changed.rowcount:
            raise ValueError("其他管理员正在处理")
    results = []
    try:
        if decision == "punish":
            current = await store.record(group_id, "message", str(data["message_id"]))
            if data.get("version") and (
                not current or current["data"].get("version") != data["version"]
            ):
                raise ValueError("消息已编辑，请复核新版本")
            results = await actions.punish(
                bot,
                group_id,
                data.get("user_id"),
                data["message_id"],
                data.get("incident", f"message:{data['message_id']}"),
                reason,
                source=source,
            )
        elif decision == "revoke":
            if not data.get("warning_event"):
                raise ValueError("复核记录没有关联警告，请从成员状态撤销指定警告")
            results.append(
                await actions.revoke_warning(
                    bot,
                    group_id,
                    data["warning_event"],
                    actor_id=actor_id,
                    source=source,
                )
            )
        elif decision in {"approve_join", "reject_join"}:
            await actions.require_right(bot, group_id, "can_invite_users")
            method = (
                bot.approve_chat_join_request
                if decision == "approve_join"
                else bot.decline_chat_join_request
            )
            await method(group_id, data["user_id"])
        status = (
            "resolved" if all(r["status"] == "success" for r in results) else "failed"
        )
    except (ValueError, TelegramError) as exc:
        status = "failed"
        results = [
            {"error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
        ]
    return await store.put_record(
        group_id,
        "review",
        key,
        data
        | {
            "state": status,
            "decision": decision,
            "source": source,
            "reason": reason,
            "results": results,
        },
    )
