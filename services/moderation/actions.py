"""The only place that executes member punishments. All callers share checks and audit."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from telegram import ChatPermissions
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut

from models import GroupGuardPendingVerification as Pending
from models import GuardEvent
from registries import engine

from . import store
from .schemas import ActionRequest


def is_uncertain_error(exc: BaseException) -> bool:
    """Return whether Telegram may have applied an operation without replying."""
    return isinstance(exc, TimedOut) or type(exc) is NetworkError


async def is_admin(bot, group_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(group_id, user_id)
    return member.status in {"creator", "administrator"}


async def require_admin(bot, group_id: int, actor_id: int | None):
    if actor_id is not None and not await is_admin(bot, group_id, actor_id):
        raise ValueError("只有当前 Telegram 群管理员可以执行此操作")


async def require_right(bot, group_id: int, right: str):
    member = await bot.get_chat_member(group_id, bot.id)
    if member.status != "creator" and (
        member.status != "administrator" or not getattr(member, right, False)
    ):
        raise ValueError(f"机器人缺少管理员权限：{right}")


def permissions_snapshot(member) -> dict:
    # Preserve existing individual restrictions, including their deadline.
    if member.status != "restricted":
        return {"permissions": None, "until": None}
    fields = ChatPermissions.__slots__
    permissions = {
        key: bool(getattr(member, key, False))
        for key in fields
        if key.startswith("can_")
    }
    until = getattr(member, "until_date", None)
    return {"permissions": permissions, "until": until.isoformat() if until else None}


async def restore_permissions(bot, group_id: int, user_id: int, snapshot: dict):
    from datetime import datetime, timezone

    chat = await bot.get_chat(group_id)
    defaults = chat.permissions.to_dict() if chat.permissions else {}
    prior = snapshot.get("permissions")
    until = datetime.fromisoformat(snapshot["until"]) if snapshot.get("until") else None
    if until and until.timestamp() > 0 and until <= datetime.now(timezone.utc):
        prior, until = None, None
    values = {
        k: bool(v) and (prior is None or prior.get(k, False))
        for k, v in defaults.items()
        if k.startswith("can_")
    }
    # Empty defaults must never translate to granting all permissions.
    await bot.restrict_chat_member(
        group_id,
        user_id,
        ChatPermissions(**values),
        until_date=until,
        use_independent_chat_permissions=True,
    )


async def execute(
    bot,
    group_id: int,
    request: ActionRequest,
    *,
    actor_id=None,
    source="web:deployment-admin",
    expected=None,
) -> dict:
    if bot is None:
        raise ValueError("Telegram 机器人尚未连接")
    async with store.lock(group_id):
        await require_admin(bot, group_id, actor_id)
        if expected:
            latest = await store.record(group_id, "message", str(request.message_id))
            expected_version = expected.get("version")
            expected_policy = expected.get("policy")
            stale_version = expected_version is not None and (
                not latest or latest["data"].get("version") != expected_version
            )
            stale_policy = (
                expected_policy is not None
                and (await store.policy(group_id)).model_dump() != expected_policy
            )
            if stale_version or stale_policy:
                raise ValueError("消息或审核策略已改变，取消过时处罚")
            if request.user_id and await store.record(
                group_id, "exempt", str(request.user_id)
            ):
                raise ValueError("成员已豁免，取消过时处罚")
        target_is_admin = bool(
            request.user_id
            and (
                request.user_id == bot.id
                or await is_admin(bot, group_id, request.user_id)
            )
        )
        if target_is_admin and request.action not in {"unban", "unwarn", "unmute"}:
            raise ValueError("不能处罚群主、管理员或本机器人")
        result = await _execute_locked(
            bot, group_id, request, source, target_is_admin=target_is_admin
        )
        if request.action == "warn" and result["status"] == "success":
            settings = await store.policy(group_id)
            active = await store.warnings(group_id, request.user_id)
            if len(active) >= settings.warning_limit:
                threshold_key = f"threshold:{active[0]['id']}"
                # Existing mute suppresses repeated threshold punishments.
                existing = await store.record(
                    group_id, "restriction", str(request.user_id)
                )
                if not existing:
                    child = ActionRequest(
                        action="mute",
                        user_id=request.user_id,
                        duration=settings.mute_seconds,
                        reason="累计警告达到阈值",
                        request_id=threshold_key,
                    )
                    escalation = await _execute_locked(
                        bot, group_id, child, "warning-threshold"
                    )
                    result["data"] = result["data"] | {"escalation": escalation}
        return result


async def _execute_locked(bot, group_id, req, source, *, target_is_admin=False):
    row, fresh = await store.event(
        group_id,
        req.action,
        source=source,
        status="running",
        reason=req.reason,
        user_id=req.user_id,
        message_id=req.message_id,
        incident=req.request_id,
    )
    if not fresh:
        return row
    data = {}
    try:
        if req.action == "warn":
            pass
        elif req.action == "unwarn":
            active = await store.warnings(group_id, req.user_id)
            target = (
                next((e for e in active if e["id"] == req.event_id), None)
                if req.event_id
                else next(iter(active), None)
            )
            if not target:
                raise ValueError("没有可撤销的有效警告")
            async with engine.new_session() as session:
                await session.execute(
                    update(GuardEvent)
                    .where(GuardEvent.id == target["id"])
                    .values(status="revoked")
                )
                await session.commit()
            data["revoked_event"] = target["id"]
        elif req.action in {"mute", "unmute", "kick", "ban", "unban"}:
            # A promoted administrator no longer accepts member restrictions.  Clearing
            # our stale bookkeeping is still safe and must not depend on a Telegram
            # permission that is no longer used for this path.
            if not (req.action == "unmute" and target_is_admin):
                await require_right(bot, group_id, "can_restrict_members")
            if req.action == "mute":
                existing = await store.record(group_id, "restriction", str(req.user_id))
                if existing:
                    raise ValueError("成员已有本系统管理的限制，请先解除或等待到期")
                member = await bot.get_chat_member(group_id, req.user_id)
                snapshot = permissions_snapshot(member)
                deadline = store.now() + timedelta(seconds=req.duration)
                data = {
                    "original": snapshot,
                    "deadline": deadline.isoformat(),
                    "trigger_warning": req.request_id.removeprefix("threshold:")
                    if source == "warning-threshold"
                    else None,
                }
                # Persist recovery material BEFORE making the external change.
                await store.put_record(
                    group_id,
                    "restriction",
                    str(req.user_id),
                    data | {"event_id": row["id"], "state": "applying"},
                )
                await bot.restrict_chat_member(
                    group_id,
                    req.user_id,
                    ChatPermissions.no_permissions(),
                    use_independent_chat_permissions=True,
                )
                await store.put_record(
                    group_id,
                    "restriction",
                    str(req.user_id),
                    data | {"event_id": row["id"], "state": "active"},
                )
                await store.task(
                    group_id,
                    "unmute",
                    deadline,
                    {"user_id": req.user_id, "event_id": row["id"]},
                )
            elif req.action == "unmute":
                restriction = await store.record(
                    group_id, "restriction", str(req.user_id)
                )
                if not restriction:
                    async with engine.new_session() as session:
                        pending = await session.get(Pending, (group_id, req.user_id))
                        if not pending or pending.state not in {
                            "pending",
                            "preparing",
                            "uncertain",
                            "restricted",
                        }:
                            raise ValueError("没有本系统可解除的禁言记录")
                        snapshot = pending.original_permissions or {}
                        token = pending.token
                    if not target_is_admin:
                        await restore_permissions(bot, group_id, req.user_id, snapshot)
                    async with engine.new_session() as session:
                        await session.execute(
                            update(Pending)
                            .where(Pending.token == token)
                            .values(state="cancelled", result="管理员解除验证限制")
                        )
                        await session.commit()
                    return await store.finish_event(
                        row["id"], "success", {"verification": "cancelled"}
                    )
                if (
                    not target_is_admin
                    and restriction["data"].get("state") == "external"
                ):
                    raise ValueError("成员权限已被其他管理员修改，无法自动恢复")
                if not target_is_admin:
                    await restore_permissions(
                        bot, group_id, req.user_id, restriction["data"]["original"]
                    )
                await store.remove_record(group_id, "restriction", str(req.user_id))
            elif req.action == "kick":
                ban_until = datetime.now(timezone.utc) + timedelta(minutes=1)
                await bot.ban_chat_member(group_id, req.user_id, until_date=ban_until)
                data["ban"] = "success"
                data["ban_until"] = ban_until.isoformat()
                await bot.unban_chat_member(group_id, req.user_id, only_if_banned=True)
            elif req.action == "ban":
                await bot.ban_chat_member(group_id, req.user_id)
            else:
                await bot.unban_chat_member(group_id, req.user_id, only_if_banned=True)
        elif req.action in {"pin", "unpin"}:
            await require_right(bot, group_id, "can_pin_messages")
            if req.action == "pin":
                await bot.pin_chat_message(
                    group_id, req.message_id, disable_notification=True
                )
            else:
                await bot.unpin_chat_message(group_id, req.message_id)
        else:
            await require_right(bot, group_id, "can_delete_messages")
            ids = (
                range(req.message_id, req.end_message_id + 1)
                if req.action == "purge"
                else [req.message_id]
            )
            deleted, failed = [], []
            for message_id in ids:
                try:
                    await bot.delete_message(group_id, message_id)
                    deleted.append(message_id)
                except RetryAfter as exc:
                    failed.append(message_id)
                    retry_after = exc.retry_after
                    if isinstance(retry_after, timedelta):
                        retry_after = retry_after.total_seconds()
                    data = {
                        "deleted": deleted,
                        "failed": failed,
                        "unattempted": [value for value in ids if value > message_id],
                        "retry_after": retry_after,
                    }
                    return await store.finish_event(
                        row["id"], "partial" if deleted else "failed", data
                    )
                except TelegramError as exc:
                    if is_uncertain_error(exc):
                        data = {
                            "deleted": deleted,
                            "failed": failed,
                            "uncertain": [message_id],
                            "unattempted": [
                                value for value in ids if value > message_id
                            ],
                        }
                        return await store.finish_event(row["id"], "uncertain", data)
                    failed.append(message_id)
            data = {"deleted": deleted, "failed": failed}
            if failed:
                return await store.finish_event(
                    row["id"], "partial" if deleted else "failed", data
                )
        return await store.finish_event(row["id"], "success", data)
    except (ValueError, TelegramError) as exc:
        # Avoid exposing provider URLs/tokens through error text.
        data["error"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        status = "uncertain" if is_uncertain_error(exc) else "failed"
        if req.action == "mute" and status == "failed":
            await store.remove_record(group_id, "restriction", str(req.user_id))
        return await store.finish_event(row["id"], status, data)


async def punish(
    bot,
    group_id,
    user_id,
    message_id,
    incident,
    reason,
    *,
    warn=True,
    source="rule",
    expected=None,
):
    results = []
    content_version = expected.get("version") if expected else None
    delete_request_id = f"delete:{message_id}"
    if content_version:
        delete_request_id += f":{content_version}"
    results.append(
        await execute(
            bot,
            group_id,
            ActionRequest(
                action="delete",
                user_id=user_id,
                message_id=message_id,
                request_id=delete_request_id,
                reason=reason,
            ),
            source=source,
            expected=expected,
        )
    )
    if warn and user_id:
        results.append(
            await execute(
                bot,
                group_id,
                ActionRequest(
                    action="warn",
                    user_id=user_id,
                    message_id=message_id,
                    request_id=incident,
                    reason=reason,
                ),
                source=source,
                expected=expected,
            )
        )
    if any(r["status"] != "success" for r in results):
        return results
    notification, fresh = await store.event(
        group_id, "notice", incident=incident, status="running", reason=reason
    )
    if fresh:
        try:
            text = f"消息已删除：{reason}" + (
                f"；成员 {user_id} 已记录警告" if warn and user_id else ""
            )
            sent = await bot.send_message(group_id, text[:3500])
            await store.task(
                group_id,
                "delete",
                store.now() + timedelta(seconds=30),
                {"message_id": sent.message_id},
            )
            await store.finish_event(notification["id"], "success", {})
        except TelegramError:
            await store.finish_event(notification["id"], "failed", {})
    return results


async def revoke_warning(
    bot, group_id, event_id, *, actor_id=None, source="web:deployment-admin"
):
    async with engine.new_session() as session:
        event = await session.get(GuardEvent, event_id)
        if not event or event.group_id != group_id or event.action != "warn":
            raise ValueError("警告事件不存在")
        user_id = event.user_id
    result = await execute(
        bot,
        group_id,
        ActionRequest(
            action="unwarn",
            user_id=user_id,
            event_id=event_id,
            reason="撤销误判",
            request_id=f"revoke:{event_id}",
        ),
        actor_id=actor_id,
        source=source,
    )
    restriction = await store.record(group_id, "restriction", str(user_id))
    settings = await store.policy(group_id)
    if (
        result["status"] == "success"
        and restriction
        and restriction["data"].get("trigger_warning")
        and len(await store.warnings(group_id, user_id)) < settings.warning_limit
    ):
        result["data"]["unmute"] = await execute(
            bot,
            group_id,
            ActionRequest(
                action="unmute",
                user_id=user_id,
                reason="撤销警告后未达到禁言阈值",
                request_id=f"revoke-mute:{event_id}",
            ),
            actor_id=actor_id,
            source=source,
        )
    return result
