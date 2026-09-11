"""Durable approval state for Telegram bot members.

The ordinary join-verification table intentionally remains human-only.  Bot
approval uses the generic guard records, reviews and tasks so it gets the same
group isolation, audit trail and restart semantics without another migration.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from telegram import ChatPermissions
from telegram.error import RetryAfter, TelegramError

from models import GuardRecord, GuardTask
from registries import engine

from . import actions, reviews, store

RECORD_KIND = "bot_approval"
STATES = frozenset(
    {"restricting", "pending", "processing", "approved", "uncertain", "rejected"}
)
# ``rejected`` rows are retained as an audit marker but disabled, so they are
# not considered active for message gating or recovery.
ACTIVE_STATES = STATES - {"rejected"}
# ``restricting`` is an in-flight/ambiguous phase and must never be replayed
# blindly after a crash.  Recovery turns it into ``uncertain``; only a record
# explicitly returned to ``pending`` (for example after RetryAfter) is safe to
# retry.
RETRYABLE_STATES = frozenset({"pending"})


def _key(user_id: int) -> str:
    return str(int(user_id))


def _user_id(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stamp(value: datetime | None) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return store.now().replace(tzinfo=timezone.utc).timestamp()
    if value is None:
        return store.now().replace(tzinfo=timezone.utc).timestamp()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _name(user) -> dict:
    return {
        "name": getattr(user, "full_name", None) or getattr(user, "first_name", ""),
        "username": getattr(user, "username", None),
        "user_id": int(user.id),
    }


def can_speak(member) -> bool:
    """Whether a live Telegram member object currently may send messages."""

    status = getattr(member, "status", None)
    if status in {"creator", "administrator"}:
        return True
    if status == "member":
        # ``ChatMemberMember`` normally has no ``is_member`` attribute, while
        # test/fallback objects sometimes include it.  Honor an explicit
        # false value so a delayed leave cannot be mistaken for approval.  A
        # few Telegram wrappers also expose ``can_send_messages`` on a plain
        # member after an external restriction edit; honor that explicit
        # value when present instead of assuming every ``member`` can speak.
        if not bool(getattr(member, "is_member", True)):
            return False
        if hasattr(member, "can_send_messages"):
            return bool(getattr(member, "can_send_messages", False))
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False)) and bool(
            getattr(member, "can_send_messages", False)
        )
    return False


def _is_admin(member) -> bool:
    return getattr(member, "status", None) in {"creator", "administrator"}


def _is_present(member) -> bool:
    status = getattr(member, "status", None)
    if status in {"creator", "administrator"}:
        return True
    if status == "member":
        return bool(getattr(member, "is_member", True))
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False


def _state(data: dict) -> str:
    return str(data.get("state", ""))


def _release_blocks(data: dict) -> bool:
    """Whether a pending release still requires fail-closed message gating."""

    state = _state(data)
    return bool(
        data.get("restricted")
        or data.get("managed") is True
        or state in {"restricting", "processing", "uncertain"}
    )


def _permission_snapshot(data: dict) -> dict | None:
    """Return a structurally valid saved permission snapshot, if present."""

    snapshot = data.get("original") or data.get("original_permissions")
    if not isinstance(snapshot, dict):
        return None
    if "permissions" not in snapshot and "until" not in snapshot:
        return None
    return snapshot


def _seconds(value) -> float:
    if isinstance(value, timedelta):
        return value.total_seconds()
    return float(value)


def retry_due(data: dict) -> datetime | None:
    """Return a stored rate-limit deadline as a naive UTC datetime."""

    value = data.get("retry_at")
    if not value:
        return None
    try:
        due = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if due.tzinfo:
        due = due.astimezone(timezone.utc).replace(tzinfo=None)
    return due


def _supersedes(
    data: dict,
    date,
    *,
    event_id=None,
    event_source=None,
    new_membership=False,
) -> bool:
    """Whether an explicit join event replaces the stored membership generation."""

    if not new_membership or (
        data.get("preapproved") and not data.get("joined_at_actual")
    ):
        return False
    # A restriction or permission lookup that may already have reached
    # Telegram is deliberately fail-closed.  A second update ID is not enough
    # evidence of a new membership in these phases; replaying it could apply a
    # second restriction after an ambiguous response.  A real leave/rejoin
    # removes the row first and therefore still gets a new generation.
    if _state(data) in {"restricting", "processing", "uncertain"}:
        return False
    prior_event_id = data.get("join_event_id")
    prior_source = data.get("join_source")
    try:
        # Service messages and chat-member updates may describe the same join.
        # Treat a cross-source observation as the duplicate half of that pair;
        # an intervening leave removes the record before a genuine rejoin.
        if event_source and prior_source and event_source != prior_source:
            # The service message and chat-member update for one join often
            # have different update IDs/sources but the same Telegram-second.
            # Only treat that pair as a duplicate within the short timestamp
            # window; a clearly later cross-source event may represent a
            # rejoin whose leave update was lost.
            if date is None:
                return False
            prior_joined = data.get("joined_at")
            if prior_joined is None or _stamp(date) - float(prior_joined) <= 2:
                return False
        if event_id is not None and prior_event_id is not None:
            return int(event_id) > int(prior_event_id)
        prior_joined = data.get("joined_at")
        return prior_joined is not None and _stamp(date) > _stamp(prior_joined)
    except (TypeError, ValueError):
        return False


@asynccontextmanager
async def _group_lock(group_id: int, lock_held: bool):
    if lock_held:
        yield
    else:
        async with store.lock(group_id):
            yield


async def _review_by_id(group_id: int, review_id: str | None) -> dict | None:
    if not review_id:
        return None
    async with engine.new_session() as session:
        row = await session.scalar(
            select(GuardRecord).where(
                GuardRecord.group_id == group_id,
                GuardRecord.kind == "review",
                GuardRecord.id == review_id,
            )
        )
        if row:
            return store.dump(row)
    # Older or hand-created records may store the review key rather than its
    # opaque database ID.  Both forms are safe within the group boundary.
    return await store.record(group_id, "review", review_id) if review_id else None


async def _update_review(
    group_id: int,
    data: dict,
    state: str,
    *,
    decision: str | None = None,
    reason: str | None = None,
    source: str = "system",
    allow_terminal=False,
):
    review = await _review_by_id(group_id, data.get("review_id"))
    if not review:
        return
    value = dict(review["data"])
    # A completed review is an audit record, not a live todo.  Release tasks
    # and late membership updates may arrive after approval/rejection; do not
    # overwrite that decision with a cleanup status.
    if value.get("state") in {"resolved", "failed", "cancelled"} and not allow_terminal:
        return
    if value.get("state") in {"resolved", "failed", "cancelled"}:
        value["previous_state"] = value.get("state")
        if value.get("decision"):
            value["previous_decision"] = value["decision"]
    value.update({"state": state, "source": source})
    if decision:
        value["decision"] = decision
    if reason:
        value["reason"] = reason
    await store.put_record(
        group_id,
        "review",
        review["key"],
        value,
        enabled=state not in {"resolved", "failed", "cancelled"},
        touch=state in {"resolved", "failed", "cancelled"},
    )


async def _save(group_id: int, user_id: int, data: dict, *, enabled=True):
    return await store.put_record(
        group_id, RECORD_KIND, _key(user_id), data, enabled=enabled
    )


async def _event(
    group_id: int,
    user_id: int,
    action: str,
    status: str,
    reason: str,
    data=None,
    *,
    source="system",
):
    await store.event(
        group_id,
        action,
        source=source,
        user_id=user_id,
        status=status,
        reason=reason,
        data=data or {},
    )


async def _schedule_retry(group_id: int, user_id: int, data: dict, delay):
    if isinstance(delay, timedelta):
        delay = delay.total_seconds()
    due = store.now() + timedelta(seconds=max(1, float(delay)))
    async with engine.new_session() as session:
        existing = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == group_id,
                    GuardTask.kind == "bot_restrict",
                    GuardTask.state.in_(["pending", "running", "uncertain"]),
                )
            )
        ).all()
        if any(
            _user_id(task.data.get("user_id")) == user_id
            and task.data.get("generation") == data.get("generation")
            for task in existing
        ):
            return
        session.add(
            GuardTask(
                id=store.uid(),
                group_id=group_id,
                kind="bot_restrict",
                due_at=due,
                data={
                    "user_id": user_id,
                    "generation": data.get("generation"),
                    "review_id": data.get("review_id"),
                },
                state="pending",
                created_at=store.now(),
            )
        )
        await session.commit()


async def _cancel_generation_tasks(
    group_id: int,
    user_id: int,
    generation,
    reason: str,
    *,
    kinds=("bot_restrict",),
):
    """Cancel durable work superseded by a confirmed administrator action."""

    async with engine.new_session() as session:
        tasks = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == group_id,
                    GuardTask.kind.in_(kinds),
                    # A running task owns the group lock while it can mutate
                    # Telegram.  It will observe/finish before this helper can
                    # run, so only queued or already-uncertain work is retired.
                    GuardTask.state.in_(["pending", "uncertain"]),
                )
            )
        ).all()
        for task in tasks:
            if (
                _user_id(task.data.get("user_id")) == user_id
                and task.data.get("generation") == generation
            ):
                task.state = "cancelled"
                task.result = reason
                task.completed_at = store.now()
        await session.commit()


async def _ensure_recovery_review(
    group_id: int, data: dict, bot=None, *, user_id: int | None = None
) -> dict:
    """Rebuild a bot todo lost in the small crash window around join setup."""

    state = _state(data)
    if state not in {"restricting", "pending", "processing", "uncertain"} and not (
        state == "approved" and data.get("release_pending")
    ):
        return data
    current = dict(data)
    if current.get("user_id") is None and user_id is not None:
        current["user_id"] = int(user_id)
    if current.get("user_id") is None:
        return current
    generation = current.get("generation") or store.uid()
    if not current.get("generation"):
        current["generation"] = generation
    review = await _review_by_id(group_id, current.get("review_id"))
    if not review:
        key = current.get("review_key") or (
            f"bot_join:{current.get('user_id') or 0}:{generation}"
        )
        review = await reviews.create(
            group_id,
            key,
            {
                "kind": "bot_join",
                "user_id": current.get("user_id"),
                "is_bot": True,
                "name": current.get("name"),
                "username": current.get("username"),
                "generation": generation,
                "reason": current.get("reason")
                or f"机器人入群待批准：{current.get('name') or current.get('user_id')}",
            },
            # Uncertain reviews intentionally stay in the Web queue until an
            # administrator verifies Telegram; pending records may receive
            # the normal in-chat buttons during startup recovery.
            bot if state == "pending" else None,
            lock_held=True,
        )
        current.update({"review_id": review["id"], "review_key": review["key"]})
        await _save(group_id, int(current["user_id"]), current)
    elif current != data:
        # Fill in identity/generation fields that may be missing from a row
        # written by an older process before the review was created.
        await _save(group_id, int(current["user_id"]), current)
    if state in {"restricting", "processing", "uncertain"}:
        await _update_review(
            group_id,
            current,
            "uncertain",
            reason=current.get("reason") or "进程中断，请核查机器人权限",
            allow_terminal=True,
        )
    elif (
        review
        and not (state == "approved" and current.get("release_pending"))
        and review["data"].get("state") in {
            "resolved",
            "failed",
            "cancelled",
            "processing",
        }
    ):
        # A crash can leave a live approval row pointing at a terminal review
        # (or a review stuck in ``processing``).  Reopen that exact generation
        # instead of silently allowing the bot or losing the Web todo.  A
        # completed approval that is only waiting for a policy-release task is
        # intentionally left terminal until the release result is known.
        await _update_review(
            group_id,
            current,
            "pending",
            reason=current.get("reason") or "机器人入群待管理员批准",
            allow_terminal=True,
        )
    return current


async def _retire_generation(group_id: int, user_id: int, data: dict):
    """Retire a superseded generation without touching Telegram permissions."""

    review = await _review_by_id(group_id, data.get("review_id"))
    if review and review["data"].get("state") not in {
        "resolved",
        "failed",
        "cancelled",
    }:
        await _update_review(
            group_id,
            data,
            "cancelled",
            reason="机器人已重新入群，旧审批代次失效",
            source="system",
        )
    await store.remove_record(group_id, RECORD_KIND, _key(user_id))
    generation = data.get("generation")
    async with engine.new_session() as session:
        tasks = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.group_id == group_id,
                    GuardTask.kind.in_(["bot_release", "bot_restrict"]),
                    GuardTask.state.in_(["pending", "running", "uncertain"]),
                )
            )
        ).all()
        for task in tasks:
            if (
                _user_id(task.data.get("user_id")) == user_id
                and task.data.get("generation") == generation
            ):
                task.state = "cancelled"
                task.result = "机器人重新入群，旧代次任务取消"
                task.completed_at = store.now()
        await session.commit()


async def _restrict(
    bot,
    group_id: int,
    user_id: int,
    data: dict,
    *,
    member=None,
    schedule_retry=True,
):
    """Apply the no-permission mask for one exact approval generation."""

    member = member or await bot.get_chat_member(group_id, user_id)
    if _is_admin(member):
        return "admin"
    if data.get("chat_type") == "group":
        raise ValueError("Telegram 仅支持在 supergroup 中逐成员限制机器人")
    await actions.require_right(bot, group_id, "can_restrict_members")
    await bot.restrict_chat_member(
        group_id,
        user_id,
        ChatPermissions.no_permissions(),
        use_independent_chat_permissions=True,
    )
    return "restricted"


async def _retry_restriction(
    bot, group_id: int, record: dict, *, schedule_retry: bool = True
):
    data = dict(record["data"])
    if _state(data) not in RETRYABLE_STATES or data.get("restricted"):
        return True
    retry_at = data.get("retry_at")
    if retry_at:
        try:
            retry_time = datetime.fromisoformat(str(retry_at))
            if retry_time.tzinfo:
                retry_time = retry_time.astimezone(timezone.utc).replace(tzinfo=None)
            if retry_time > store.now():
                if schedule_retry:
                    await _schedule_retry(
                        group_id,
                        int(record["key"]),
                        data,
                        (retry_time - store.now()).total_seconds(),
                    )
                return False
        except (TypeError, ValueError):
            pass
    try:
        member = None
        # A rate-limited membership lookup happens before the original snapshot
        # was available.  Capture it on the first safe retry, otherwise
        # approval would restore chat defaults instead of the bot's actual
        # pre-join permissions.
        if data.get("original_captured") is False:
            member = await bot.get_chat_member(group_id, int(record["key"]))
            snapshot = actions.permissions_snapshot(member)
            data["original"] = snapshot
            data["original_permissions"] = snapshot
            data["original_captured"] = True
            await _save(group_id, int(record["key"]), data)
        # Persist the ambiguous phase before the call that can mutate Telegram.
        # A crash from this point must recover as uncertain, while an explicit
        # RetryAfter below returns the record to a safely retryable state.
        data.pop("retry_at", None)
        data.pop("retry_after", None)
        data["state"] = "restricting"
        await _save(group_id, int(record["key"]), data)
        result = await _restrict(
            bot, group_id, int(record["key"]), data, member=member
        )
    except RetryAfter as exc:
        delay = _seconds(exc.retry_after)
        data.update(
            {
                "state": "pending",
                "restricted": False,
                "managed": False,
                "retry_after": delay,
                "retry_at": (store.now() + timedelta(seconds=delay)).isoformat(),
            }
        )
        await _save(group_id, int(record["key"]), data)
        if schedule_retry:
            await _schedule_retry(group_id, int(record["key"]), data, exc.retry_after)
        else:
            raise
        return False
    except (TelegramError, ValueError) as exc:
        state = "uncertain" if actions.is_uncertain_error(exc) else "pending"
        data.update(
            {
                "state": state,
                "restricted": False,
                # A definitive failure did not apply a Telegram restriction.
                # For an uncertain response, retain an explicit unknown value
                # so release/recovery never treats it as a confirmed success.
                "managed": None if state == "uncertain" else False,
            }
        )
        await _save(group_id, int(record["key"]), data)
        await _event(
            group_id,
            int(record["key"]),
            "bot_approval",
            "uncertain" if state == "uncertain" else "failed",
            type(exc).__name__,
        )
        if state == "uncertain":
            await _update_review(group_id, data, "uncertain", reason=type(exc).__name__)
        return False
    data.update(
        {
            "state": "approved" if result == "admin" else "pending",
            "restricted": result != "admin",
            "managed": result != "admin",
        }
    )
    if result == "admin":
        data["approved_by"] = "administrator"
    data.pop("retry_at", None)
    data.pop("retry_after", None)
    await _save(group_id, int(record["key"]), data)
    if result == "admin":
        await _cancel_generation_tasks(
            group_id,
            int(record["key"]),
            data.get("generation"),
            "机器人已成为管理员，限制任务取消",
        )
        await _update_review(group_id, data, "resolved", decision="approve_bot", source="external")
    return True


async def retry_restriction(
    bot, group_id: int, record: dict, *, schedule_retry: bool = True
):
    """Public worker entry point for a confirmed, retryable restriction."""

    return await _retry_restriction(
        bot, group_id, record, schedule_retry=schedule_retry
    )


async def joined(
    bot,
    chat,
    user,
    date=None,
    *,
    settings=None,
    lock_held=False,
    event_id=None,
    event_source=None,
    new_membership=False,
):
    """Record and restrict a newly joined bot, idempotently."""

    if not getattr(user, "is_bot", False) or user.id == getattr(bot, "id", None):
        return True
    new_membership = bool(new_membership or event_id is not None)
    settings = settings or await store.policy(chat.id)
    if not getattr(settings, "bot_join_approval_enabled", True):
        return True
    async with _group_lock(chat.id, lock_held):
        live = None
        try:
            live = await bot.get_chat_member(chat.id, user.id)
        except (TelegramError, ValueError) as exc:
            # A missing update or a transient lookup must not silently grant
            # access.  Keep a durable uncertain record and let first-message
            # reconciliation retry it.
            existing = await store.record(chat.id, RECORD_KIND, _key(user.id))
            if existing and _state(existing["data"]) in ACTIVE_STATES:
                if not _supersedes(
                    existing["data"],
                    date,
                    event_id=event_id,
                    event_source=event_source,
                    new_membership=new_membership,
                ):
                    return True
                await _retire_generation(chat.id, user.id, existing["data"])
            generation = store.uid()
            rate_limited = isinstance(exc, RetryAfter)
            uncertain = actions.is_uncertain_error(exc)
            retry_after = _seconds(exc.retry_after) if rate_limited else None
            data = {
                **_name(user),
                "generation": generation,
                "joined_at": _stamp(date),
                "original": {"permissions": None, "until": None},
                "original_permissions": {"permissions": None, "until": None},
                "original_captured": False,
                "state": "pending" if rate_limited else ("uncertain" if uncertain else "pending"),
                "restricted": False,
                "managed": None if uncertain else False,
                "chat_type": getattr(chat, "type", None),
                "reason": type(exc).__name__,
            }
            if event_id is not None:
                data["join_event_id"] = int(event_id)
            if event_source:
                data["join_source"] = event_source
            if retry_after is not None:
                data.update(
                    {
                        "retry_after": retry_after,
                        "retry_at": (
                            store.now() + timedelta(seconds=retry_after)
                        ).isoformat(),
                    }
                )
            # Persist the generation before creating/sending its review.  If
            # the process stops in between, startup recovery can rebuild the
            # missing todo instead of leaving an orphan Telegram notification.
            await _save(chat.id, user.id, data)
            review = await reviews.create(
                chat.id,
                f"bot_join:{user.id}:{generation}",
                {
                    "kind": "bot_join",
                    "user_id": user.id,
                    "is_bot": True,
                    "name": data.get("name"),
                    "username": data.get("username"),
                    "generation": generation,
                    "reason": f"机器人入群待批准：{data.get('name') or user.id}",
                },
                bot,
                lock_held=True,
            )
            data["review_id"], data["review_key"] = review["id"], review["key"]
            await _save(chat.id, user.id, data)
            if rate_limited:
                await _schedule_retry(chat.id, user.id, data, exc.retry_after)
            await _event(
                chat.id,
                user.id,
                "bot_approval",
                "uncertain" if uncertain else "failed",
                type(exc).__name__,
                {"generation": generation, "retry_after": retry_after}
                if rate_limited
                else {"generation": generation},
            )
            if uncertain:
                await _update_review(
                    chat.id,
                    data,
                    "uncertain",
                    reason=type(exc).__name__,
                )
            return uncertain

        # A delayed join update can arrive after Telegram already reports the
        # bot as left/kicked.  Do not create a live approval generation for a
        # member who is no longer in the chat.
        if not _is_present(live):
            return True

        existing = await store.record(chat.id, RECORD_KIND, _key(user.id))
        if existing and existing["enabled"]:
            current_chat_type = getattr(chat, "type", None)
            if (
                current_chat_type
                and existing["data"].get("chat_type") != current_chat_type
            ):
                refreshed = dict(existing["data"])
                refreshed["chat_type"] = current_chat_type
                await _save(chat.id, user.id, refreshed)
                existing = await store.record(chat.id, RECORD_KIND, _key(user.id))
        supersedes = False
        if (
            existing
            and existing["enabled"]
            and _supersedes(
                existing["data"],
                date,
                event_id=event_id,
                event_source=event_source,
                new_membership=new_membership,
            )
        ):
            supersedes = True
        if supersedes:
            await _retire_generation(chat.id, user.id, existing["data"])
            existing = None

        if _is_admin(live):
            if existing and _state(existing["data"]) in ACTIVE_STATES:
                data = dict(existing["data"])
            else:
                snapshot = actions.permissions_snapshot(live)
                data = {
                    **_name(user),
                    "generation": store.uid(),
                    "joined_at": _stamp(date),
                    "original": snapshot,
                    "original_permissions": snapshot,
                }
            if event_id is not None:
                data["join_event_id"] = int(event_id)
            if event_source:
                data["join_source"] = event_source
            data.update({"state": "approved", "restricted": False, "managed": False, "approved_by": "administrator"})
            # If the policy was briefly disabled and then re-enabled while a
            # release task was pending, an administrator promotion is a fresh
            # explicit approval for this generation.  Do not leave the stale
            # release marker blocking the newly promoted bot.
            data.pop("release_pending", None)
            await _save(chat.id, user.id, data)
            await _cancel_generation_tasks(
                chat.id,
                user.id,
                data.get("generation"),
                "机器人已成为管理员，限制任务取消",
            )
            await _update_review(chat.id, data, "resolved", decision="approve_bot", source="external")
            return True

        if existing is None:
            existing = await store.record(chat.id, RECORD_KIND, _key(user.id))
        if existing and existing["enabled"] and _state(existing["data"]) in ACTIVE_STATES:
            # A duplicate join update commonly carries a stale ``member``
            # object in test clients and in Telegram races.  Only an explicit
            # membership permission update can grant external approval; never
            # infer it from a repeated join notification.
            if not existing["data"].get("restricted") and _state(existing["data"]) in RETRYABLE_STATES:
                return await _retry_restriction(bot, chat.id, existing)
            elif _state(existing["data"]) == "approved" and existing["data"].get("preapproved"):
                data = dict(existing["data"])
                data.update({"joined_at": _stamp(date), "joined_at_actual": True})
                if event_id is not None:
                    data["join_event_id"] = int(event_id)
                if event_source:
                    data["join_source"] = event_source
                await _save(chat.id, user.id, data)
            return True

        generation = store.uid()
        original = actions.permissions_snapshot(live)
        data = {
            **_name(user),
            "generation": generation,
            "joined_at": _stamp(date),
            "original": original,
            "original_permissions": original,
            "original_captured": True,
            "state": "restricting",
            "restricted": False,
            # Flip to True only after the restriction API succeeds.  This lets
            # a definitive permission/basic-group failure be released without
            # making another Telegram mutation.
            "managed": False,
            "chat_type": getattr(chat, "type", None),
        }
        if event_id is not None:
            data["join_event_id"] = int(event_id)
        if event_source:
            data["join_source"] = event_source
        await _save(chat.id, user.id, data)
        review = await reviews.create(
            chat.id,
            f"bot_join:{user.id}:{generation}",
            {
                "kind": "bot_join",
                "user_id": user.id,
                "is_bot": True,
                "name": data.get("name"),
                "username": data.get("username"),
                "generation": generation,
                "reason": f"机器人入群待批准：{data.get('name') or user.id}",
            },
            bot,
            lock_held=True,
        )
        data["review_id"], data["review_key"] = review["id"], review["key"]
        await _save(chat.id, user.id, data)
        try:
            # Let ``_restrict`` inspect the authoritative target member first.
            # An administrator bot is already approved even in a basic group;
            # only ordinary bots should receive the unsupported-group failure.
            result = await _restrict(bot, chat.id, user.id, data, member=live)
            if result == "admin":
                data.update({"state": "approved", "restricted": False, "managed": False, "approved_by": "administrator"})
                await _save(chat.id, user.id, data)
                await _cancel_generation_tasks(
                    chat.id,
                    user.id,
                    generation,
                    "机器人已成为管理员，限制任务取消",
                )
                await _update_review(chat.id, data, "resolved", decision="approve_bot", source="external")
            else:
                data.update({"state": "pending", "restricted": True, "managed": True})
                await _save(chat.id, user.id, data)
            await _event(chat.id, user.id, "bot_approval", "success", "机器人已限制，等待批准", {"generation": generation})
        except RetryAfter as exc:
            data.update(
                {
                    "state": "pending",
                    "restricted": False,
                    "managed": False,
                    "retry_after": _seconds(exc.retry_after),
                    "retry_at": (
                        store.now() + timedelta(seconds=_seconds(exc.retry_after))
                    ).isoformat(),
                }
            )
            await _save(chat.id, user.id, data)
            await _schedule_retry(chat.id, user.id, data, exc.retry_after)
            await _event(
                chat.id,
                user.id,
                "bot_approval",
                "failed",
                "RetryAfter",
                {
                    "generation": generation,
                    "retry_after": _seconds(exc.retry_after),
                },
            )
            return False
        except (TelegramError, ValueError) as exc:
            uncertain = actions.is_uncertain_error(exc)
            data.update(
                {
                    "state": "uncertain" if uncertain else "pending",
                    "restricted": False,
                    "managed": None if uncertain else False,
                    "reason": type(exc).__name__,
                }
            )
            await _save(chat.id, user.id, data)
            await _event(chat.id, user.id, "bot_approval", "uncertain" if uncertain else "failed", type(exc).__name__, {"generation": generation})
            if uncertain:
                await _update_review(chat.id, data, "uncertain", reason=type(exc).__name__)
            return uncertain
        return True


async def ensure_message(bot, chat, user, message=None, *, settings=None) -> bool:
    """Reconcile an unannounced join and return whether the message is blocked."""

    if not getattr(user, "is_bot", False) or user.id == getattr(bot, "id", None):
        return False
    settings = settings or await store.policy(chat.id)
    approval_enabled = getattr(settings, "bot_join_approval_enabled", True)
    record = None
    if not approval_enabled:
        # Policy changes deliberately queue an asynchronous release.  Until a
        # confirmed release completes, a bot that may still be restricted must
        # remain blocked; otherwise it could speak in the small window between
        # the PATCH and the worker's Telegram call.
        record = await store.record(chat.id, RECORD_KIND, _key(user.id))
        if not record or not record["enabled"] or not _release_blocks(record["data"]):
            return False
        # An administrator promotion is an explicit approval even while the
        # asynchronous release is pending.  Reconcile it immediately so an
        # old release task cannot keep an admin bot blocked.
        try:
            live_admin = await bot.get_chat_member(chat.id, user.id)
        except (TelegramError, ValueError):
            live_admin = None
        if live_admin is not None and _is_admin(live_admin):
            await external_permission_change(chat.id, live_admin, lock_held=False)
            return False
    live = None
    if approval_enabled:
        try:
            live = await bot.get_chat_member(chat.id, user.id)
        except (TelegramError, ValueError):
            # ``joined`` creates/retains an uncertain record.  We still stop this
            # update: a lookup failure is never evidence of approval.
            try:
                await joined(
                    bot, chat, user, getattr(message, "date", None), settings=settings
                )
            except (TelegramError, ValueError) as exc:
                await _event(
                    chat.id,
                    user.id,
                    "bot_approval",
                    "uncertain" if actions.is_uncertain_error(exc) else "failed",
                    type(exc).__name__,
                )
        else:
            if _is_admin(live):
                existing = await store.record(chat.id, RECORD_KIND, _key(user.id))
                if existing:
                    await external_permission_change(chat.id, live, lock_held=False)
                else:
                    await joined(
                        bot,
                        chat,
                        user,
                        getattr(message, "date", None),
                        settings=settings,
                    )
                return False
            if record is None:
                record = await store.record(chat.id, RECORD_KIND, _key(user.id))
            if (
                record
                and record["enabled"]
                and _state(record["data"]) == "approved"
                and not record["data"].get("release_pending")
            ):
                return False
            if not record or not record["enabled"] or _state(record["data"]) not in ACTIVE_STATES:
                await joined(bot, chat, user, getattr(message, "date", None), settings=settings)
            elif (
                can_speak(live)
                and _state(record["data"]) != "approved"
                and record["data"].get("chat_type") != "group"
                and record["data"].get("managed") is True
                and (
                    getattr(live, "status", None) == "restricted"
                    or (
                        # A real ``ChatMemberMember`` has no per-member
                        # ``can_send_messages`` field.  Its appearance after
                        # a confirmed restriction is therefore authoritative
                        # evidence of an external unrestriction.  Keep the
                        # explicit-field branch conservative for lightweight
                        # doubles that may not reflect our mock restriction.
                        getattr(live, "status", None) == "member"
                        and not hasattr(live, "can_send_messages")
                    )
                )
            ):
                # A few Telegram update modes omit the membership event. Once we
                # know this generation was actually restricted by us, an
                # authoritative live member that can speak is evidence of an
                # external restore. Duplicate join updates do not use this path;
                # they are reconciled by ``joined`` under the generation guard.
                await external_permission_change(chat.id, live, lock_held=False)
                return False
            elif (
                not record["data"].get("release_pending")
                and not record["data"].get("restricted")
                and _state(record["data"]) in RETRYABLE_STATES
            ):
                # Re-read under the group lease: policy release or an admin
                # decision may race the first-message reconciliation.
                async with store.lock(chat.id):
                    latest = await store.record(chat.id, RECORD_KIND, _key(user.id))
                    if (
                        latest
                        and latest["enabled"]
                        and not latest["data"].get("release_pending")
                        and not latest["data"].get("restricted")
                        and _state(latest["data"]) in RETRYABLE_STATES
                    ):
                        await _retry_restriction(bot, chat.id, latest)
                        # The retry may discover that Telegram has promoted
                        # the bot to an administrator.  In that case the
                        # current message is already explicitly approved;
                        # do not delete it merely because the join update was
                        # missing or rate-limited.
                        refreshed = await store.record(
                            chat.id, RECORD_KIND, _key(user.id)
                        )
                        if (
                            refreshed
                            and refreshed["enabled"]
                            and _state(refreshed["data"]) == "approved"
                            and not refreshed["data"].get("release_pending")
                        ):
                            return False

    try:
        await actions.require_right(bot, chat.id, "can_delete_messages")
        if message is not None:
            await bot.delete_message(chat.id, message.message_id)
        await _event(chat.id, user.id, "bot_message", "success", "未批准机器人消息已删除")
    except (TelegramError, ValueError) as exc:
        await _event(
            chat.id,
            user.id,
            "bot_message",
            "uncertain" if actions.is_uncertain_error(exc) else "failed",
            type(exc).__name__,
        )
    return True


async def external_permission_change(
    group_id: int,
    member,
    *,
    lock_held=False,
    date=None,
    event_id=None,
):
    """Treat administrator promotion/manual unrestriction as approval."""

    user = getattr(member, "user", None)
    if not user or not getattr(user, "is_bot", False):
        return False
    async with _group_lock(group_id, lock_held):
        record = await store.record(group_id, RECORD_KIND, _key(user.id))
        if not record or _state(record["data"]) not in ACTIVE_STATES:
            return False
        joined_event_id = record["data"].get("join_event_id")
        if event_id is not None and joined_event_id is not None:
            try:
                if int(event_id) < int(joined_event_id):
                    return False
            except (TypeError, ValueError):
                pass
        joined_at = record["data"].get("joined_at")
        if date is not None and joined_at is not None:
            try:
                if _stamp(date) < _stamp(joined_at):
                    return False
            except (TypeError, ValueError):
                pass
        if (
            record["data"].get("chat_type") == "group"
            and not _is_admin(member)
        ):
            # Basic groups cannot have a per-member speaking restriction, so
            # a normal ``member`` status is not proof of external approval.
            return False
        if not (_is_admin(member) or can_speak(member)):
            return False
        data = dict(record["data"])
        data.update(
            {
                "state": "approved",
                "restricted": False,
                "managed": False,
                "approved_by": "external",
            }
        )
        release_pending = bool(data.get("release_pending"))
        settings = await store.policy(group_id) if release_pending else None
        if release_pending and getattr(
            settings, "bot_join_approval_enabled", True
        ):
            # The old approval cycle was waiting to be released, but an
            # administrator has now explicitly granted permission after the
            # feature was re-enabled.  This is a fresh external approval.
            data.pop("release_pending", None)
        await _save(group_id, user.id, data)
        await _cancel_generation_tasks(
            group_id,
            user.id,
            data.get("generation"),
            "管理员已在 Telegram 外部批准机器人",
            kinds=("bot_restrict", "bot_release"),
        )
        await _update_review(
            group_id,
            data,
            "resolved",
            decision="bot_release"
            if release_pending
            and not getattr(settings, "bot_join_approval_enabled", True)
            else "approve_bot",
            source="external",
        )
        if release_pending and not getattr(
            settings, "bot_join_approval_enabled", True
        ):
            # Approval is currently disabled, so the external permission
            # change also completes the queued release.  Remove the old cycle
            # exactly as a successful worker release would.
            await store.remove_record(group_id, RECORD_KIND, _key(user.id))
        await _event(
            group_id,
            user.id,
            "bot_release" if release_pending else "bot_approval",
            "success",
            "管理员外部恢复机器人权限"
            if release_pending
            else "管理员外部批准机器人发言",
            {"generation": data.get("generation")},
            source="external",
        )
        return True


async def mark_join_request_approved(
    group_id: int,
    user_id: int,
    *,
    user=None,
    date=None,
    lock_held=False,
    review_id=None,
    review_key=None,
):
    """Persist pre-approval from Telegram's join-request workflow."""

    async with _group_lock(group_id, lock_held):
        if not getattr(
            await store.policy(group_id), "bot_join_approval_enabled", True
        ):
            return None
        existing = await store.record(group_id, RECORD_KIND, _key(user_id))
        if (
            existing
            and _state(existing["data"]) == "approved"
            and existing["data"].get("preapproved")
            and not existing["data"].get("joined_at_actual")
        ):
            data = dict(existing["data"])
        else:
            if existing and _state(existing["data"]) in ACTIVE_STATES:
                # A join request describes a membership that has not started.
                # Any active non-preapproval belongs to an older membership.
                await _retire_generation(group_id, user_id, existing["data"])
            data = {
                "user_id": int(user_id),
                "name": getattr(user, "full_name", None) if user else None,
                "username": getattr(user, "username", None) if user else None,
                "generation": store.uid(),
                "joined_at": _stamp(date),
                "original": {"permissions": None, "until": None},
                "original_permissions": {"permissions": None, "until": None},
                "preapproved": True,
                "managed": False,
            }
        data.update(
            {
                "state": "approved",
                "restricted": False,
                "managed": False,
                "approved_by": "join_request",
                "preapproved": True,
            }
        )
        if review_id:
            data["review_id"] = review_id
        if review_key:
            data["review_key"] = review_key
        await _save(group_id, user_id, data)
        await _update_review(
            group_id,
            data,
            "resolved",
            decision="approve_bot",
            reason="通过入群申请批准机器人",
            source="join_request",
        )
        return data


async def decide(
    bot,
    group_id: int,
    review_data: dict,
    decision: str,
    reason: str,
    *,
    source: str = "system",
):
    """Execute one generation-checked bot review decision."""

    user_id = int(review_data["user_id"])
    generation = review_data.get("generation")
    async with store.lock(group_id):
        record = await store.record(group_id, RECORD_KIND, _key(user_id))
        if (
            not generation
            or not record
            or not record["enabled"]
            or record["data"].get("generation") != generation
        ):
            raise ValueError("机器人审批代次已更新，拒绝使用旧复核按钮")
        data = dict(record["data"])
        if data.get("release_pending"):
            raise ValueError("机器人审批正在释放，不能使用旧复核按钮")
        if _state(data) != "pending":
            raise ValueError("机器人审批已处理或需要先核查不确定结果")
        data["state"] = "processing"
        await _save(group_id, user_id, data)
        try:
            if decision == "approve_bot":
                live = None
                if (
                    data.get("restricted")
                    or data.get("managed") is True
                    or data.get("original_captured") is False
                ):
                    # A promotion is an approval in its own right.  Check the
                    # authoritative member before trying to restore a
                    # restriction; an administrator cannot be restored via
                    # ``restrictChatMember`` and may no longer grant that
                    # permission to the moderation bot.
                    live = await bot.get_chat_member(group_id, user_id)
                    if _is_admin(live):
                        data.update(
                            {
                                "state": "approved",
                                "restricted": False,
                                "managed": False,
                                "approved_by": "administrator",
                            }
                        )
                        data.pop("release_pending", None)
                        await _save(group_id, user_id, data)
                        await _cancel_generation_tasks(
                            group_id,
                            user_id,
                            generation,
                            "机器人已成为管理员，限制任务取消",
                            kinds=("bot_restrict", "bot_release"),
                        )
                        await store.event(
                            group_id,
                            "bot_approval",
                            source=source,
                            user_id=user_id,
                            status="success",
                            reason=reason,
                            data={"generation": generation, "decision": decision},
                        )
                        return {
                            "status": "success",
                            "reason": "机器人管理员身份已批准发言",
                            "generation": generation,
                        }
                snapshot = _permission_snapshot(data)
                if data.get("original_captured") is False:
                    # The initial member lookup was rate-limited.  Do not
                    # restore a made-up chat-default snapshot and accidentally
                    # change permissions that the bot had before joining.
                    live = live or await bot.get_chat_member(group_id, user_id)
                    snapshot = actions.permissions_snapshot(live)
                    data.update(
                        {
                            "original": snapshot,
                            "original_permissions": snapshot,
                            "original_captured": True,
                        }
                    )
                    snapshot = _permission_snapshot(data)
                # A definitive restriction failure leaves no Telegram-side
                # mutation to undo.  An explicit administrator approval can
                # therefore finish that pending generation without requiring
                # a right that was never available; confirmed restrictions do
                # still require the normal restore permission.
                if data.get("restricted") or data.get("managed") is True:
                    if snapshot is None:
                        raise ValueError("机器人原始权限快照缺失，不能安全恢复")
                    await actions.require_right(bot, group_id, "can_restrict_members")
                    await actions.restore_permissions(
                        bot, group_id, user_id, snapshot
                    )
                data.update(
                    {
                        "state": "approved",
                        "restricted": False,
                        "managed": False,
                        "approved_by": "administrator",
                    }
                )
                await _save(group_id, user_id, data)
                await _cancel_generation_tasks(
                    group_id,
                    user_id,
                    generation,
                    "管理员已批准机器人，限制任务取消",
                )
                await store.event(
                    group_id,
                    "bot_approval",
                    source=source,
                    user_id=user_id,
                    status="success",
                    reason=reason,
                    data={"generation": generation, "decision": decision},
                )
                return {"status": "success", "reason": "机器人已批准发言", "generation": generation}
            if decision != "reject_bot":
                raise ValueError("无效的机器人审批决定")
            # Both temporary banning and the subsequent unban are restricted
            # member operations.  Check the same Telegram capability used by
            # the join restriction path before issuing either mutation so a
            # missing right remains a durable pending failure.
            await actions.require_right(bot, group_id, "can_restrict_members")
            until = store.now().replace(tzinfo=timezone.utc) + timedelta(seconds=60)
            await bot.ban_chat_member(group_id, user_id, until_date=until)
            await bot.unban_chat_member(group_id, user_id, only_if_banned=True)
            data.update({"state": "rejected", "restricted": False, "rejected_by": "administrator"})
            await _save(group_id, user_id, data, enabled=False)
            await _cancel_generation_tasks(
                group_id,
                user_id,
                generation,
                "管理员已移出机器人，限制任务取消",
            )
            await store.event(
                group_id,
                "bot_approval",
                source=source,
                user_id=user_id,
                status="success",
                reason=reason,
                data={"generation": generation, "decision": decision},
            )
            return {"status": "success", "reason": "机器人已移出群组", "generation": generation}
        except RetryAfter:
            data["state"] = "pending"
            await _save(group_id, user_id, data)
            raise
        except (TelegramError, ValueError) as exc:
            uncertain = actions.is_uncertain_error(exc)
            data.update({"state": "uncertain" if uncertain else "pending", "reason": type(exc).__name__})
            await _save(group_id, user_id, data)
            await store.event(
                group_id,
                "bot_approval",
                source=source,
                user_id=user_id,
                status="uncertain" if uncertain else "failed",
                reason=type(exc).__name__,
                data={"generation": generation},
            )
            if uncertain:
                await _update_review(group_id, data, "uncertain", reason=type(exc).__name__)
            raise


async def left(
    group_id: int,
    user_id: int,
    date=None,
    *,
    lock_held=False,
    event_id=None,
):
    """Clear only the generation that was present at the departure timestamp."""

    async with _group_lock(group_id, lock_held):
        record = await store.record(group_id, RECORD_KIND, _key(user_id))
        if not record:
            return False
        joined_event_id = record["data"].get("join_event_id")
        if event_id is not None and joined_event_id is not None:
            try:
                if int(event_id) < int(joined_event_id):
                    return False
            except (TypeError, ValueError):
                pass
        joined_at = record["data"].get("joined_at")
        if joined_at is not None:
            try:
                joined_timestamp = float(joined_at)
            except (TypeError, ValueError):
                joined_timestamp = _stamp(datetime.fromisoformat(str(joined_at)))
            # A departure at the same timestamp is the normal leave event for
            # this generation.  Only a strictly older event is stale; the
            # generic runtime join_seen guard handles the common delayed-leave
            # ordering where the replacement generation has a newer second.
            if joined_timestamp > _stamp(date):
                return False
        review = await _review_by_id(group_id, record["data"].get("review_id"))
        if review and review["data"].get("state") not in {
            "resolved",
            "failed",
            "cancelled",
        }:
            await _update_review(
                group_id,
                record["data"],
                "cancelled",
                reason="机器人已离群",
                source="system",
            )
        await store.remove_record(group_id, RECORD_KIND, _key(user_id))
        async with engine.new_session() as session:
            tasks = (
                await session.scalars(
                    select(GuardTask).where(
                        GuardTask.group_id == group_id,
                        GuardTask.kind.in_(["bot_release", "bot_restrict"]),
                        GuardTask.state.in_(["pending", "running", "uncertain"]),
                    )
                )
            ).all()
            for task in tasks:
                if _user_id(task.data.get("user_id")) == user_id and task.data.get("generation") == record["data"].get("generation"):
                    task.state = "cancelled"
                    task.result = "机器人已离群，任务取消"
                    task.completed_at = store.now()
            await session.commit()
        return True


async def release_task(bot, job: dict):
    """Release one bot after approval is disabled; raises for unsafe outcomes."""

    group_id, data = job["group_id"], job["data"]
    user_id, generation = int(data["user_id"]), data.get("generation")
    async with store.lock(group_id):
        record = await store.record(group_id, RECORD_KIND, _key(user_id))
        if not record or record["data"].get("generation") != generation:
            return "stale"
        # Re-enabling approval and externally restoring/promoting the bot can
        # clear ``release_pending`` while an already-claimed release task is
        # still waiting on this lease.  That task belongs to the old cycle and
        # must not remove the fresh approved record.
        current_policy = await store.policy(group_id)
        if (
            getattr(current_policy, "bot_join_approval_enabled", True)
            and not record["data"].get("release_pending")
        ):
            return "stale"
        if record["data"].get("restricted") or record["data"].get("managed") is True:
            # A promotion can happen while the release worker is queued and
            # the corresponding ChatMember update may be missing.  An
            # authoritative administrator status is an explicit approval and
            # must not be sent through a restore call that Telegram rejects
            # for administrator targets.
            try:
                live_admin = await bot.get_chat_member(group_id, user_id)
            except (TelegramError, ValueError):
                live_admin = None
            if live_admin is not None and _is_admin(live_admin):
                await external_permission_change(
                    group_id, live_admin, lock_held=True
                )
                return "released"
        current = await _ensure_recovery_review(
            group_id, dict(record["data"]), bot=None, user_id=user_id
        )
        if _state(current) in {"uncertain", "processing", "restricting"}:
            # The previous Telegram call may already have changed the member.
            # Keep the release task and review actionable for an administrator;
            # never issue a compensating permission mutation blindly.
            await _update_review(
                group_id,
                current,
                "uncertain",
                reason="机器人权限结果不确定，请人工核查",
                source="scheduler",
                allow_terminal=True,
            )
            return "uncertain"
        if _state(current) == "rejected":
            await store.remove_record(group_id, RECORD_KIND, _key(user_id))
            return "released"
        if current.get("preapproved") and not current.get("joined_at_actual"):
            await _update_review(
                group_id,
                current,
                "resolved",
                decision="bot_release",
                reason="已关闭机器人入群审批",
                source="system",
            )
            await store.remove_record(group_id, RECORD_KIND, _key(user_id))
            return "released"
        if current.get("managed") is not True and not current.get("restricted"):
            await _update_review(
                group_id,
                current,
                "resolved",
                decision="bot_release",
                reason="机器人未被本系统确认限制，审批记录已释放",
                source="system",
            )
            await store.remove_record(group_id, RECORD_KIND, _key(user_id))
            return "released"
        if current.get("chat_type") == "group":
            # Basic groups cannot have per-member restrictions; there is no
            # Telegram-side state to restore, so close the durable approval
            # record while retaining its audit/review entry.
            await _update_review(
                group_id,
                current,
                "resolved",
                decision="bot_release",
                reason="基础群不支持逐成员限制，审批记录已释放",
                source="system",
            )
            await store.remove_record(group_id, RECORD_KIND, _key(user_id))
            return "released"
        current["state"] = "processing"
        await _save(group_id, user_id, current)
        try:
            snapshot = _permission_snapshot(current)
            if snapshot is None:
                raise ValueError("机器人原始权限快照缺失，不能安全恢复")
            await actions.require_right(bot, group_id, "can_restrict_members")
            await actions.restore_permissions(
                bot,
                group_id,
                user_id,
                snapshot,
            )
        except RetryAfter as exc:
            delay = _seconds(exc.retry_after)
            current.update(
                {
                    "state": "pending",
                    "retry_after": delay,
                    "retry_at": (store.now() + timedelta(seconds=delay)).isoformat(),
                }
            )
            await _save(group_id, user_id, current)
            await _event(
                group_id,
                user_id,
                "bot_release",
                "failed",
                "RetryAfter",
                {"generation": generation, "retry_after": delay},
                source="scheduler",
            )
            raise
        except (TelegramError, ValueError) as exc:
            uncertain = actions.is_uncertain_error(exc)
            current["state"] = "uncertain" if uncertain else "pending"
            if uncertain:
                current["managed"] = None
            current.pop("retry_at", None)
            current.pop("retry_after", None)
            await _save(group_id, user_id, current)
            await _event(
                group_id,
                user_id,
                "bot_release",
                "uncertain" if uncertain else "failed",
                type(exc).__name__,
                {"generation": generation},
                source="scheduler",
            )
            if uncertain:
                await _update_review(
                    group_id,
                    current,
                    "uncertain",
                    reason=type(exc).__name__,
                    allow_terminal=True,
                )
            raise
        await _update_review(group_id, current, "resolved", decision="bot_release", reason="已关闭机器人入群审批", source="system")
        await store.remove_record(group_id, RECORD_KIND, _key(user_id))
        await _event(
            group_id,
            user_id,
            "bot_release",
            "success",
            "机器人审批已关闭并恢复权限",
            {"generation": generation},
            source="scheduler",
        )
        return "released"


async def recover(bot=None):
    """Reconcile interrupted bot state and recreate missing release jobs."""

    groups: set[int] = set()
    interrupted: list[tuple[int, dict]] = []
    row_keys: set[tuple[int, int | None, object]] = set()
    async with engine.new_session() as session:
        rows = (
            await session.scalars(select(GuardRecord).where(GuardRecord.kind == RECORD_KIND))
        ).all()
        interrupted_tasks = (
            await session.scalars(
                select(GuardTask).where(
                    GuardTask.kind.in_(["bot_restrict", "bot_release"]),
                    GuardTask.state == "uncertain",
                )
            )
        ).all()
        uncertain_tasks = {}
        for task in interrupted_tasks:
            task_user_id = _user_id(task.data.get("user_id"))
            key = (
                task.group_id,
                task_user_id,
                task.data.get("generation"),
            )
            uncertain_tasks.setdefault(key, []).append(task)
        for row in rows:
            groups.add(row.group_id)
            state = _state(row.data)
            try:
                row_user_id = int(row.key)
            except (TypeError, ValueError):
                # A malformed legacy row must not prevent the worker from
                # recovering every other group's approval state.
                continue
            key = (row.group_id, row_user_id, row.data.get("generation"))
            row_keys.add(key)
            matching_uncertain = uncertain_tasks.get(key, [])
            rate_limit_recovery = (
                row.enabled
                and state == "pending"
                and retry_due(row.data) is not None
                and key in uncertain_tasks
            )
            if rate_limit_recovery:
                due = retry_due(row.data) or store.now()
                for task in uncertain_tasks[key]:
                    task.state = "pending"
                    task.due_at = due
                    task.result = "恢复已确认的 Telegram 限流任务"
                    task.completed_at = None
                continue
            if matching_uncertain and state in {"approved", "rejected"}:
                if state == "approved" and row.data.get("release_pending"):
                    # The worker may have crashed after claiming a release
                    # task but before persisting ``processing`` on the
                    # approval row.  A restore call may or may not have
                    # reached Telegram, so fail closed and surface this exact
                    # generation in the review queue.
                    row.data = dict(row.data) | {
                        "state": "uncertain",
                        "managed": None,
                        "reason": "进程中断，请核查机器人恢复结果",
                    }
                    interrupted.append((row.group_id, dict(row.data)))
                else:
                    # An uncertain restriction task left behind after an
                    # external approval (or a rejected/removed bot) has no
                    # Telegram mutation left to replay. Retire the stale
                    # task so it cannot remain stuck forever.
                    for task in matching_uncertain:
                        task.state = "cancelled"
                        task.result = "机器人审批代次已结束，任务取消"
                        task.completed_at = store.now()
                continue
            if row.enabled and (
                state in {"restricting", "processing"}
                or (
                    state not in {"approved", "rejected"}
                    and key in uncertain_tasks
                )
            ):
                row.data = dict(row.data) | {
                    "state": "uncertain",
                    "reason": "进程中断，请核查机器人权限",
                }
                interrupted.append((row.group_id, dict(row.data)))
        # A successful release can remove its approval row just before the
        # worker persists the task's terminal state.  The common recovery pass
        # deliberately marks that task uncertain; retire it here instead of
        # leaving an orphaned actionable item forever.  No Telegram operation
        # is replayed because the generation record is absent.
        for key, tasks in uncertain_tasks.items():
            if key in row_keys:
                continue
            for task in tasks:
                task.state = "cancelled"
                task.result = "机器人审批记录不存在，任务取消"
                task.completed_at = store.now()
        await session.commit()
    for group_id, data in interrupted:
        await _update_review(
            group_id,
            data,
            "uncertain",
            reason="进程中断，请核查机器人权限",
        )
    for group_id in groups:
        settings = await store.policy(group_id)
        async with store.lock(group_id), engine.new_session() as session:
            rows = (
                await session.scalars(
                    select(GuardRecord).where(
                        GuardRecord.group_id == group_id,
                        GuardRecord.kind == RECORD_KIND,
                        GuardRecord.enabled.is_(True),
                    )
                )
            ).all()
            jobs = (
                await session.scalars(
                    select(GuardTask).where(
                        GuardTask.group_id == group_id,
                        GuardTask.kind.in_(["bot_release", "bot_restrict"]),
                        GuardTask.state.in_(["pending", "running", "uncertain"]),
                    )
                )
            ).all()
            release_generations = {
                (_user_id(job.data.get("user_id")), job.data.get("generation"))
                for job in jobs
                if job.kind == "bot_release"
            }
            restrict_generations = {
                (_user_id(job.data.get("user_id")), job.data.get("generation"))
                for job in jobs
                if job.kind == "bot_restrict"
            }
            for row in rows:
                try:
                    row_user_id = int(row.key)
                except (TypeError, ValueError):
                    continue
                recovered = await _ensure_recovery_review(
                    group_id,
                    dict(row.data),
                    user_id=row_user_id,
                    bot=(
                        bot
                        if getattr(
                            settings, "bot_join_approval_enabled", True
                        )
                        and not row.data.get("release_pending")
                        else None
                    ),
                )
                if recovered != row.data:
                    row.data = recovered
                generation = row.data.get("generation")
                if not generation:
                    continue
                release_required = bool(
                    row.data.get("release_pending")
                    or not getattr(settings, "bot_join_approval_enabled", True)
                )
                if release_required:
                    if not row.data.get("release_pending"):
                        row.data = dict(row.data) | {"release_pending": True}
                    if (row_user_id, generation) in release_generations:
                        continue
                if not release_required and (
                    _state(row.data) == "pending"
                    and not row.data.get("restricted")
                    and not row.data.get("release_pending")
                    and (row_user_id, generation) not in restrict_generations
                ):
                    session.add(
                        GuardTask(
                            id=store.uid(),
                            group_id=group_id,
                            kind="bot_restrict",
                            due_at=retry_due(row.data) or store.now(),
                            data={
                                "user_id": row_user_id,
                                "generation": generation,
                                "review_id": row.data.get("review_id"),
                            },
                            state="pending",
                            created_at=store.now(),
                        )
                    )
                    restrict_generations.add((row_user_id, generation))
                    continue
                if not release_required:
                    continue
                session.add(
                    GuardTask(
                        id=store.uid(),
                        group_id=group_id,
                        kind="bot_release",
                        due_at=store.now(),
                        data={
                            "user_id": row_user_id,
                            "generation": generation,
                            "original": row.data.get("original")
                            or row.data.get("original_permissions"),
                            "original_permissions": row.data.get("original_permissions")
                            or row.data.get("original"),
                            "review_id": row.data.get("review_id"),
                        },
                        state="pending",
                        created_at=store.now(),
                    )
                )
            await session.commit()


async def approval_status(group_id: int, user_id: int) -> dict | None:
    return await store.record(group_id, RECORD_KIND, _key(user_id))


async def allowed_for_moderation(bot, group_id: int, user_id: int, settings=None) -> bool:
    settings = settings or await store.policy(group_id)
    if not getattr(settings, "bot_moderation_enabled", False):
        return False
    if user_id == getattr(bot, "id", None):
        return False
    if await actions.is_admin(bot, group_id, user_id):
        return False
    exempt = await store.record(group_id, "exempt", _key(user_id))
    if exempt and exempt["enabled"]:
        return False
    record = await approval_status(group_id, user_id)
    if record and record["enabled"]:
        if record["data"].get("release_pending") or _release_blocks(record["data"]):
            return False
    if getattr(settings, "bot_join_approval_enabled", True):
        return bool(
            record
            and record["enabled"]
            and _state(record["data"]) == "approved"
            and not record["data"].get("release_pending")
        )
    return True


# Small public aliases keep the service convenient for handlers/tests that use
# the same vocabulary as the human verification service.
start = joined
member_left = left
message = ensure_message
release = release_task
