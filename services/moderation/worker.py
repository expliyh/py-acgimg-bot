"""Database-backed schedules, with at-most-once dispatch for ambiguous sends."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from telegram.error import TelegramError

from models import GroupGuardPendingVerification as Pending
from models import GuardEvent, GuardRecord, GuardTask
from registries import engine

from . import actions, ai, store, verification
from .schemas import ActionRequest, Content

logger = logging.getLogger(__name__)


def next_occurrence(due, repeat, timezone_name, clock=None):
    clock = clock or store.now()
    local = due.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(timezone_name))
    step = timedelta(days=7 if repeat == "weekly" else 1)
    while True:
        local += step
        candidate = local.astimezone(timezone.utc).replace(tzinfo=None)
        if candidate > clock:
            return candidate


async def save_content(group_id, value: Content):
    async with store.lock(group_id):
        record = await store.put_record(
            group_id,
            value.kind,
            value.name,
            value.model_dump(mode="json"),
            value.enabled,
        )
        if value.kind == "announcement":
            async with engine.new_session() as session:
                jobs = (
                    await session.scalars(
                        select(GuardTask).where(
                            GuardTask.group_id == group_id,
                            GuardTask.kind == "announcement",
                            GuardTask.state == "pending",
                        )
                    )
                ).all()
                for job in jobs:
                    if job.data.get("name") == value.name:
                        job.state = "cancelled"
                await session.commit()
            if value.enabled:
                await store.task(
                    group_id,
                    "announcement",
                    value.due_at,
                    {"name": value.name, "revision": record["data"]},
                )
        return record


async def set_state(job_id, state, result=""):
    async with engine.new_session() as session:
        await session.execute(
            update(GuardTask)
            .where(GuardTask.id == job_id)
            .values(state=state, result=result[:2000])
        )
        await session.commit()


class Worker:
    def __init__(self, bot):
        self.bot, self.runner = bot, None
        self.children = set()
        self.last_cleanup = None

    async def start(self):
        if not self.runner:
            await self.recover()
            self.runner = asyncio.create_task(self.run())

    async def stop(self):
        if self.runner:
            self.runner.cancel()
        for child in self.children:
            child.cancel()
        await asyncio.gather(
            *([self.runner] if self.runner else []),
            *self.children,
            return_exceptions=True,
        )
        self.runner = None

    async def recover(self):
        async with engine.new_session() as session:
            await session.execute(
                update(GuardTask)
                .where(GuardTask.state == "running")
                .values(state="uncertain", result="进程中断，结果需核查")
            )
            await session.execute(
                update(GuardEvent)
                .where(GuardEvent.status == "running")
                .values(status="uncertain")
            )
            await session.execute(
                update(Pending)
                .where(Pending.state.in_(["preparing", "processing"]))
                .values(state="uncertain", result="处理被中断，请管理员核查权限")
            )
            values = [
                store.dump(row)
                for row in (
                    await session.scalars(
                        select(Pending).where(Pending.state == "pending")
                    )
                ).all()
            ]
            restrictions = [
                store.dump(row)
                for row in (
                    await session.scalars(
                        select(GuardRecord).where(GuardRecord.kind == "restriction")
                    )
                ).all()
            ]
            review_rows = (
                await session.scalars(
                    select(GuardRecord).where(GuardRecord.kind == "review")
                )
            ).all()
            for review in review_rows:
                if review.data.get("state") == "processing":
                    review.data = review.data | {
                        "state": "uncertain",
                        "reason": "处理被中断，请核查实际结果",
                    }
            await session.commit()
        for row in values:
            await store.task(
                row["group_id"],
                "verify",
                row["expires_at"],
                {"user_id": row["user_id"], "token": row["token"]},
            )
        for row in restrictions:
            if row["data"].get("deadline") and row["data"].get("state") == "active":
                await store.task(
                    row["group_id"],
                    "unmute",
                    datetime.fromisoformat(row["data"]["deadline"]),
                    {"user_id": int(row["key"]), "event_id": row["data"]["event_id"]},
                )

    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Moderation worker tick failed")
            await asyncio.sleep(1)

    async def tick(self):
        config = await store.ai_config()
        async with engine.new_session() as session:
            due = (
                await session.scalars(
                    select(GuardTask)
                    .where(
                        GuardTask.state == "pending",
                        GuardTask.kind != "ai",
                        GuardTask.due_at <= store.now(),
                    )
                    .order_by(GuardTask.due_at)
                    .limit(20)
                )
            ).all()
            ai_jobs = (
                await session.scalars(
                    select(GuardTask)
                    .where(
                        GuardTask.state == "pending",
                        GuardTask.kind == "ai",
                        GuardTask.due_at <= store.now(),
                    )
                    .order_by(GuardTask.due_at)
                    .limit(max(0, config.concurrency - len(self.children)))
                )
            ).all()
            jobs = [store.dump(job) for job in [*due, *ai_jobs]]
        for job in jobs:
            async with engine.new_session() as session:
                result = await session.execute(
                    update(GuardTask)
                    .where(GuardTask.id == job["id"], GuardTask.state == "pending")
                    .values(state="running")
                )
                await session.commit()
                if not result.rowcount:
                    continue
            if job["kind"] == "ai":
                child = asyncio.create_task(self.dispatch(job))
                self.children.add(child)
                child.add_done_callback(self.children.discard)
            else:
                await self.dispatch(job)
        if self.last_cleanup is None or self.last_cleanup < store.now() - timedelta(
            hours=1
        ):
            await self.cleanup()
            self.last_cleanup = store.now()

    async def dispatch(self, job):
        data, group_id, kind = job["data"], job["group_id"], job["kind"]
        try:
            result = "success"
            if kind == "ai":
                result = await ai.process(self.bot, job)
            elif kind == "verify":
                result = await verification.finish(
                    self.bot, group_id, data["user_id"], data["token"], expired=True
                )
            elif kind == "delete":
                await actions.require_right(self.bot, group_id, "can_delete_messages")
                await self.bot.delete_message(group_id, data["message_id"])
            elif kind == "unmute":
                record = await store.record(
                    group_id, "restriction", str(data["user_id"])
                )
                if record and record["data"]["event_id"] == data["event_id"]:
                    result = await actions.execute(
                        self.bot,
                        group_id,
                        ActionRequest(
                            action="unmute",
                            user_id=data["user_id"],
                            request_id=f"expire:{data['event_id']}",
                        ),
                        source="scheduler",
                    )
                    if result["status"] != "success":
                        await set_state(
                            job["id"], result["status"], str(result["data"])
                        )
                        return
                    result = "禁言已到期解除"
            elif kind == "announcement":
                await self.announce(job)
                return
            await set_state(job["id"], "done", str(result))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Moderation task %s failed", job["id"])
            await set_state(
                job["id"],
                "uncertain" if isinstance(exc, TelegramError) else "failed",
                type(exc).__name__,
            )
            await store.event(
                group_id,
                "task",
                status="failed",
                reason=type(exc).__name__,
                data={"task_id": job["id"], "kind": kind},
            )

    async def announce(self, job):
        group_id, data = job["group_id"], job["data"]
        async with store.lock(group_id):
            record = await store.record(group_id, "announcement", data["name"])
            if (
                not record
                or not record["enabled"]
                or record["data"] != data["revision"]
            ):
                await set_state(job["id"], "cancelled")
                return
            value = Content.model_validate(record["data"])
            late = store.now() - job["due_at"] > timedelta(minutes=5)
            if not late:
                await self.bot.send_message(group_id, value.text)
            await set_state(job["id"], "missed" if late else "done")
            if value.repeat != "once":
                await store.task(
                    group_id,
                    "announcement",
                    next_occurrence(job["due_at"], value.repeat, value.timezone),
                    data,
                )

    async def cleanup(self):
        async with engine.new_session() as session:
            groups = (
                await session.scalars(select(GuardEvent.group_id).distinct())
            ).all()
        for group_id in groups:
            settings = await store.policy(group_id)
            cutoff = store.now() - timedelta(
                days=max(settings.log_days, settings.warning_days)
            )
            async with engine.new_session() as session:
                await session.execute(
                    delete(GuardEvent).where(
                        GuardEvent.group_id == group_id, GuardEvent.created_at < cutoff
                    )
                )
                await session.execute(
                    delete(GuardTask).where(
                        GuardTask.group_id == group_id,
                        GuardTask.state.in_(["done", "cancelled", "missed"]),
                        GuardTask.created_at < cutoff,
                    )
                )
                await session.execute(
                    delete(GuardRecord).where(
                        GuardRecord.group_id == group_id,
                        GuardRecord.kind.in_(["message", "join_seen"]),
                        GuardRecord.created_at < store.now() - timedelta(days=2),
                    )
                )
                await session.commit()
