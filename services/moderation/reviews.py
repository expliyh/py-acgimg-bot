from datetime import timedelta

from sqlalchemy import update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter, TelegramError

from models import GuardRecord
from registries import engine

from . import actions, store


async def create(group_id, key, data, bot=None, *, lock_held=False):
    async def save():
        existing = await store.record(group_id, "review", key)
        if existing:
            return existing, False
        row = await store.put_record(
            group_id, "review", key, data | {"state": "pending"}
        )
        return row, True

    if lock_held:
        row, fresh = await save()
    else:
        async with store.lock(group_id):
            row, fresh = await save()
    if bot and fresh:
        buttons = (
            [("批准", "approve_join"), ("拒绝", "reject_join")]
            if data.get("kind") == "join"
            else [("批准发言", "approve_bot"), ("移出机器人", "reject_bot")]
            if data.get("kind") == "bot_join"
            else [("处罚", "punish"), ("忽略", "dismiss")]
        )
        try:
            if data.get("kind") == "bot_join":
                identity = f"机器人 {data.get('name') or data.get('user_id')}"
                if data.get("username"):
                    identity += f" @{data['username']}"
                identity += f"（ID {data.get('user_id')}）"
                text = f"待管理员复核 #{row['id'][:8]}\n{identity}\n{data.get('reason', '')[:900]}"
            else:
                text = f"待管理员复核 #{row['id'][:8]}\n{data.get('reason', '成员举报')[:1000]}"
            sent = await bot.send_message(
                group_id,
                text,
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
            # Bot approvals have no timeout.  Keep the in-chat review message
            # available until an administrator decides or the bot leaves; the
            # Web page remains the durable source even if Telegram later
            # prunes ordinary review notifications.
            if data.get("kind") != "bot_join":
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
        if data["state"] not in {"pending", "uncertain"}:
            raise ValueError("该记录已处理或正在处理")
        if data["state"] == "uncertain" and decision != "dismiss":
            raise ValueError("结果不确定的复核只能在人工核查后关闭")
        kind = data.get("kind")
        if kind == "bot_join":
            valid = decision in {"approve_bot", "reject_bot"} or (
                decision == "dismiss" and data["state"] == "uncertain"
            )
        elif kind == "join":
            valid = decision in {"approve_join", "reject_join", "dismiss"}
        else:
            valid = decision in {"punish", "revoke", "dismiss"}
        if not valid:
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
                expected={"version": data["version"]} if data.get("version") else None,
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
            method = (
                bot.approve_chat_join_request
                if decision == "approve_join"
                else bot.decline_chat_join_request
            )
            if data.get("is_bot") and decision == "approve_join":
                # Telegram can emit the membership update immediately after
                # approve_chat_join_request returns. Hold the group lease over
                # both calls so the update cannot restrict the bot before the
                # durable pre-approval marker is written.
                from . import bot_approval

                async with store.lock(group_id):
                    await actions.require_right(bot, group_id, "can_invite_users")
                    await method(group_id, data["user_id"])
                    await bot_approval.mark_join_request_approved(
                        group_id,
                        data["user_id"],
                        date=data.get("requested_at"),
                        lock_held=True,
                        review_id=review_id,
                        review_key=key,
                    )
            else:
                await actions.require_right(bot, group_id, "can_invite_users")
                await method(group_id, data["user_id"])
        elif decision in {"approve_bot", "reject_bot"}:
            from . import bot_approval

            result = await bot_approval.decide(
                bot,
                group_id,
                data,
                decision,
                reason,
                source=source,
            )
            results = [result]
        statuses = {result.get("status") for result in results}
        if "uncertain" in statuses:
            status = "uncertain"
        else:
            status = (
                "resolved"
                if all(result.get("status") == "success" for result in results)
                else "failed"
            )
    except (ValueError, TelegramError) as exc:
        if (
            decision in {"approve_bot", "reject_bot"}
            and isinstance(exc, ValueError)
            and ("代次已更新" in str(exc) or "正在释放" in str(exc))
        ):
            # Do not turn a stale Telegram button into a successful-looking
            # pending decision.  A concurrent leave/rejoin may already have
            # cancelled the old review; never resurrect that audit row.  If the
            # generation is still current but a release is in progress, keep
            # it actionable only as a pending informational row.
            current_review = await store.record(group_id, "review", key)
            from . import bot_approval

            approval = await bot_approval.approval_status(
                group_id, int(data.get("user_id", 0))
            )
            generation_stale = not approval or approval["data"].get(
                "generation"
            ) != data.get("generation")
            current_data = (
                dict(current_review["data"])
                if current_review
                else dict(data)
            )
            if current_data.get("state") in {"resolved", "failed", "cancelled"}:
                raise
            if generation_stale:
                current_data.update(
                    {
                        "state": "cancelled",
                        "decision": decision,
                        "source": source,
                        "reason": str(exc),
                        "results": [{"error": str(exc)}],
                    }
                )
                await store.put_record(
                    group_id,
                    "review",
                    key,
                    current_data,
                    enabled=False,
                    touch=True,
                )
            else:
                current_data.update(
                    {
                        "state": "pending",
                        "decision": decision,
                        "source": source,
                        "reason": str(exc),
                        "results": [{"error": str(exc)}],
                    }
                )
                await store.put_record(
                    group_id, "review", key, current_data, enabled=True
                )
            raise
        if isinstance(exc, RetryAfter) and decision in {
            "approve_join",
            "reject_join",
            "approve_bot",
            "reject_bot",
        }:
            status = "pending"  # Telegram rejected this attempt; keep the review actionable.
        elif decision in {"approve_bot", "reject_bot"}:
            # Missing rights, a definitive Telegram rejection, or a malformed
            # restore snapshot are failures of this attempt, not proof that
            # the bot was approved.  Keep the review and approval record
            # pending for a later retry.  If the service already marked the
            # Telegram call uncertain, preserve that fail-closed state instead
            # of making the button actionable.
            from . import bot_approval

            approval = await bot_approval.approval_status(
                group_id, int(data.get("user_id", 0))
            )
            current_review = await store.record(group_id, "review", key)
            approval_state = approval["data"].get("state") if approval else None
            if approval_state in {"approved", "rejected"} or (
                approval and not approval["enabled"]
            ):
                # An external administrator (or another decision) may have
                # completed the generation while this button was in flight.
                # Never resurrect that todo as a pending action.
                if current_review and current_review["data"].get("state") in {
                    "resolved",
                    "failed",
                    "cancelled",
                }:
                    return current_review
                status = "resolved"
                data = dict(current_review["data"] if current_review else data)
                data["decision"] = (
                    "approve_bot" if approval_state == "approved" else "reject_bot"
                )
                results = [{"status": "success", "external": True}]
            elif not approval:
                if current_review and current_review["data"].get("state") in {
                    "resolved",
                    "failed",
                    "cancelled",
                }:
                    return current_review
                status = "cancelled"
            else:
                status = (
                    "uncertain"
                    if approval_state == "uncertain"
                    else "pending"
                )
        else:
            status = "uncertain" if actions.is_uncertain_error(exc) else "failed"
        if not results:
            results = [
                {
                    "error": str(exc)
                    if isinstance(exc, ValueError)
                    else type(exc).__name__
                }
            ]
    terminal = status in {"resolved", "failed", "cancelled"}
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
        enabled=not terminal,
        touch=terminal,
    )
