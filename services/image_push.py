"""Durable multi-group image push plans and their Telegram worker."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import asc, desc, func, select, update
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut

from defines import GroupStatus
from models import Group, ImagePushBatch, ImagePushDelivery, ImagePushPlan, Illustration
from registries import engine, illust_registry
from services import pixiv
from services.illustration_importer import import_illustration
from services.image_service import resource_for_illustration
from services.permissions import has_super_user_access
from services.storage_service import use as use_storage
from utils import ensure_list_length

logger = logging.getLogger(__name__)

PID_PATTERN = re.compile(r"^(?P<pid>[1-9][0-9]*)(?::(?P<page>[1-9][0-9]*))?$")
REPEATS = {"once", "daily", "weekly", "interval"}
MODES = {"fixed_same", "fixed_different", "random_same", "random_different"}
BATCH_TERMINAL = {"success", "partial", "failed", "skipped", "uncertain", "cancelled"}
_PID_IMPORT_LOCKS: dict[int, asyncio.Lock] = {}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid() -> str:
    return uuid.uuid4().hex


def parse_pid_spec(value: object) -> tuple[int, int | None]:
    """Parse ``pid[:page]`` and return a Pixiv id plus a one-based page."""

    match = PID_PATTERN.fullmatch(str(value).strip()) if value is not None else None
    if not match:
        raise ValueError("PID 必须为正整数，可选页码格式为 pid:page")
    pid = int(match.group("pid"))
    page = int(match.group("page")) if match.group("page") else None
    return pid, page


def normalize_pid_spec(value: object) -> str:
    pid, page = parse_pid_spec(value)
    return f"{pid}:{page}" if page is not None else str(pid)


def to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def next_occurrence(
    due_at: datetime,
    repeat: str,
    timezone_name: str,
    *,
    interval_seconds: int | None = None,
    clock: datetime | None = None,
) -> datetime:
    """Calculate the next local-calendar occurrence as naive UTC."""

    clock = clock or now()
    if repeat == "interval":
        if not interval_seconds:
            raise ValueError("固定间隔必须提供 interval_seconds")
        candidate = due_at + timedelta(seconds=interval_seconds)
        while candidate <= clock:
            candidate += timedelta(seconds=interval_seconds)
        return candidate
    local = due_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(timezone_name))
    step = timedelta(days=7 if repeat == "weekly" else 1)
    candidate_local = local + step
    candidate = candidate_local.astimezone(timezone.utc).replace(tzinfo=None)
    while candidate <= clock:
        candidate_local += step
        candidate = candidate_local.astimezone(timezone.utc).replace(tzinfo=None)
    return candidate


def _dump(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _config_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    result = {
        "target_scope": value["target_scope"],
        "group_ids": list(value.get("group_ids") or []),
        "mode": value["mode"],
    }
    if value.get("pid") is not None:
        result["pid"] = normalize_pid_spec(value["pid"])
    if value.get("pid_by_group") is not None:
        result["pid_by_group"] = {
            str(group_id): normalize_pid_spec(spec)
            for group_id, spec in (value.get("pid_by_group") or {}).items()
        }
    return result


async def existing_group_ids(group_ids: list[int]) -> set[int]:
    if not group_ids:
        return set()
    async with engine.new_session() as session:
        rows = (await session.scalars(select(Group.id).where(Group.id.in_(group_ids)))).all()
    return {int(item) for item in rows}


async def create_plan(value: dict[str, Any]) -> ImagePushPlan:
    repeat = value["repeat"]
    due_at = to_utc_naive(value["due_at"])
    interval = value.get("interval_seconds")
    if repeat not in REPEATS:
        raise ValueError("不支持的重复方式")
    if repeat == "interval" and not 60 <= int(interval or 0) <= 2_592_000:
        raise ValueError("固定间隔必须在 60 秒至 30 天之间")
    if repeat != "interval":
        interval = None
    plan = ImagePushPlan(
        id=uid(),
        name=str(value["name"]).strip(),
        enabled=bool(value.get("enabled", True)),
        repeat=repeat,
        due_at=due_at,
        next_run_at=due_at,
        interval_seconds=interval,
        timezone=value["timezone"],
        target_scope=value["target_scope"],
        group_ids=list(value.get("group_ids") or []),
        mode=value["mode"],
        pid=normalize_pid_spec(value["pid"]) if value.get("pid") is not None else None,
        pid_by_group={
            str(group_id): normalize_pid_spec(spec)
            for group_id, spec in (value.get("pid_by_group") or {}).items()
        }
        if value.get("pid_by_group") is not None
        else None,
    )
    async with engine.new_session() as session:
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
    return plan


async def get_plan(plan_id: str) -> ImagePushPlan | None:
    async with engine.new_session() as session:
        return await session.get(ImagePushPlan, plan_id)


async def list_plans(*, limit: int = 25, offset: int = 0) -> tuple[int, list[ImagePushPlan]]:
    async with engine.new_session() as session:
        total = await session.scalar(select(func.count()).select_from(ImagePushPlan))
        rows = (
            await session.scalars(
                select(ImagePushPlan)
                .order_by(desc(ImagePushPlan.created_at), desc(ImagePushPlan.id))
                .offset(offset)
                .limit(limit)
            )
        ).all()
    return int(total or 0), list(rows)


async def update_plan(plan_id: str, values: dict[str, Any]) -> ImagePushPlan | None:
    async with engine.new_session() as session:
        plan = await session.get(ImagePushPlan, plan_id)
        if plan is None:
            return None
        if "name" in values:
            plan.name = str(values["name"]).strip()
        if "enabled" in values:
            plan.enabled = bool(values["enabled"])
        if "repeat" in values:
            plan.repeat = values["repeat"]
        if "timezone" in values:
            plan.timezone = values["timezone"]
        if "due_at" in values and values["due_at"] is not None:
            plan.due_at = to_utc_naive(values["due_at"])
            plan.next_run_at = plan.due_at
        if "interval_seconds" in values:
            interval = values["interval_seconds"]
            if plan.repeat == "interval" and not 60 <= int(interval or 0) <= 2_592_000:
                raise ValueError("固定间隔必须在 60 秒至 30 天之间")
            plan.interval_seconds = interval
        elif plan.repeat != "interval":
            plan.interval_seconds = None
        if "target_scope" in values:
            plan.target_scope = values["target_scope"]
        if "group_ids" in values:
            plan.group_ids = list(values["group_ids"] or [])
        if "mode" in values:
            plan.mode = values["mode"]
        if "pid" in values:
            plan.pid = normalize_pid_spec(values["pid"]) if values["pid"] else None
        if "pid_by_group" in values:
            plan.pid_by_group = {
                str(group_id): normalize_pid_spec(spec)
                for group_id, spec in (values["pid_by_group"] or {}).items()
            }
        await session.commit()
        await session.refresh(plan)
    if not plan.enabled:
        await cancel_pending_batches(plan_id)
    return plan


async def cancel_plan(plan_id: str) -> bool:
    async with engine.new_session() as session:
        plan = await session.get(ImagePushPlan, plan_id)
        if plan is None:
            return False
        plan.enabled = False
        await session.commit()
    await cancel_pending_batches(plan_id)
    return True


async def cancel_pending_batches(plan_id: str) -> None:
    async with engine.new_session() as session:
        rows = (
            await session.scalars(
                select(ImagePushBatch).where(
                    ImagePushBatch.plan_id == plan_id,
                    ImagePushBatch.state == "pending",
                )
            )
        ).all()
        for row in rows:
            row.state = "cancelled"
            row.result = "计划已停用，任务取消"
            row.completed_at = now()
        await session.commit()


async def create_batch(
    value: dict[str, Any], *, trigger: str = "manual", plan_id: str | None = None,
    due_at: datetime | None = None,
) -> ImagePushBatch:
    snapshot = _config_snapshot(value)
    if due_at is None:
        batch_due_at = now()
    elif due_at.tzinfo is not None:
        batch_due_at = to_utc_naive(due_at)
    else:
        batch_due_at = due_at
    batch = ImagePushBatch(
        id=uid(),
        plan_id=plan_id,
        trigger=trigger,
        state="pending",
        due_at=batch_due_at,
        config_snapshot=snapshot,
        summary={},
        created_at=now(),
    )
    async with engine.new_session() as session:
        session.add(batch)
        await session.commit()
        await session.refresh(batch)
    return batch


async def create_batch_from_plan(
    plan_id: str,
    *,
    trigger: str = "auto",
    due_at: datetime | None = None,
) -> ImagePushBatch | None:
    plan = await get_plan(plan_id)
    if plan is None:
        return None
    value = {
        "target_scope": plan.target_scope,
        "group_ids": plan.group_ids or [],
        "mode": plan.mode,
        "pid": plan.pid,
        "pid_by_group": plan.pid_by_group,
    }
    return await create_batch(
        value,
        trigger=trigger,
        plan_id=plan.id,
        due_at=plan.next_run_at if due_at is None else due_at,
    )


async def get_batch(batch_id: str) -> ImagePushBatch | None:
    async with engine.new_session() as session:
        return await session.get(ImagePushBatch, batch_id)


async def list_batches(
    *, limit: int = 25, offset: int = 0, plan_id: str | None = None,
    trigger: str | None = None, state: str | None = None,
) -> tuple[int, list[ImagePushBatch]]:
    async with engine.new_session() as session:
        conditions = []
        if plan_id:
            conditions.append(ImagePushBatch.plan_id == plan_id)
        if trigger:
            conditions.append(ImagePushBatch.trigger == trigger)
        if state:
            conditions.append(ImagePushBatch.state == state)
        count_stmt = select(func.count()).select_from(ImagePushBatch).where(*conditions)
        stmt = (
            select(ImagePushBatch)
            .where(*conditions)
            .order_by(desc(ImagePushBatch.created_at), desc(ImagePushBatch.id))
            .offset(offset)
            .limit(limit)
        )
        total = await session.scalar(count_stmt)
        rows = (await session.scalars(stmt)).all()
    return int(total or 0), list(rows)


async def deliveries(batch_id: str) -> list[ImagePushDelivery]:
    async with engine.new_session() as session:
        rows = (
            await session.scalars(
                select(ImagePushDelivery)
                .where(ImagePushDelivery.batch_id == batch_id)
                .order_by(asc(ImagePushDelivery.created_at), asc(ImagePushDelivery.id))
            )
        ).all()
    return list(rows)


async def _ensure_illustration(pid: int, locks: dict[int, asyncio.Lock]) -> Illustration:
    lock = locks.setdefault(pid, asyncio.Lock())
    async with lock:
        illust = await illust_registry.get_illust_info(pid)
        if illust is not None:
            return illust
        cached = getattr(lock, "_image_push_illustration", None)
        if cached is not None:
            return cached
        if not pixiv.enabled:
            raise RuntimeError("Pixiv 功能未启用，无法自动导入指定 PID")
        result = await import_illustration(pid, bot=None, telegram_chat_ids=None)
        # Keep the result on the per-PID lock as a guard for mocked/failed
        # persistence paths too; production imports persist before returning.
        lock._image_push_illustration = result.illustration
        return result.illustration


async def _random_illustration(sanity_limit: int, allow_r18g: bool) -> Illustration | None:
    return await illust_registry.random_illust(
        sanity_limit=sanity_limit, r18g=allow_r18g
    )


async def _bot_can_send_photo(bot: Any, group_id: int) -> tuple[bool, str | None]:
    bot_id = getattr(bot, "id", None)
    if bot_id is None:
        return True, None
    try:
        member = await bot.get_chat_member(group_id, bot_id)
    except TelegramError as exc:
        return False, f"无法读取机器人权限：{type(exc).__name__}"
    except Exception as exc:
        logger.warning("Failed to read bot permissions for group %s: %s", group_id, exc)
        return False, f"无法读取机器人权限：{type(exc).__name__}"
    status = str(getattr(member, "status", ""))
    if status in {"left", "kicked", "banned"}:
        return False, "机器人不在该群或已被移出"
    for field in ("can_send_messages", "can_send_photos"):
        if getattr(member, field, None) is False:
            return False, "机器人没有发送图片权限"
    # Non-admin members do not expose media permissions on ChatMember; fall
    # back to the chat's default permissions in that case.
    if status in {"member", "restricted"}:
        try:
            chat = await bot.get_chat(group_id)
        except TelegramError as exc:
            return False, f"无法读取群组发图权限：{type(exc).__name__}"
        except Exception as exc:
            logger.warning("Failed to read chat permissions for group %s: %s", group_id, exc)
            return False, f"无法读取群组发图权限：{type(exc).__name__}"
        permissions = getattr(chat, "permissions", None)
        if permissions is not None:
            for field in ("can_send_messages", "can_send_photos"):
                if getattr(permissions, field, None) is False:
                    return False, "机器人没有发送图片权限"
    return True, None


async def _image_policy_reason(group_id: int, illust: Illustration) -> str | None:
    """Re-check the group policy immediately before the Telegram call."""

    async with engine.new_session() as session:
        group = await session.get(Group, group_id)
    reason = _group_block_reason(group)
    if reason:
        return reason
    if illust.sanity_level > int(group.sanity_limit):
        return "图片过滤等级超过该群限制"
    if illust.r18g and not group.allow_r18g:
        return "该群不允许 R18G 图片"
    return None


def _group_block_reason(group: Group | None) -> str | None:
    if group is None:
        return "群组不存在或已删除"
    status = getattr(group, "status", None)
    status_value = getattr(status, "value", status)
    if status == GroupStatus.BLOCKED or status_value in {
        GroupStatus.BLOCKED.value,
        "blocked",
        "BLOCKED",
    }:
        return "群组已被阻塞"
    if (
        status == GroupStatus.DISABLED
        or status_value in {GroupStatus.DISABLED.value, "disabled", "DISABLED"}
        or not group.enable
    ):
        return "群组已停用"
    if not group.allow_setu:
        return "群组已关闭图片功能"
    return None


def group_push_block_reason(group: Group | None) -> str | None:
    """Return a user-facing reason when a group cannot receive a push."""

    return _group_block_reason(group)


def _page_index(illust: Illustration, requested_page: int | None) -> int:
    count = int(illust.page_count or 0)
    if count <= 0:
        raise ValueError("作品没有可用图片页面")
    if requested_page is None:
        return random.randrange(count)
    if requested_page < 1 or requested_page > count:
        raise ValueError(f"页码超出范围（作品共 {count} 页）")
    return requested_page - 1


def _pixiv_metadata_lines(illust: Illustration, image_link: str) -> list[str]:
    """Return source metadata to show below a Pixiv image caption.

    Manually uploaded illustrations use the same send pipeline as Pixiv
    illustrations, but their IDs are internal values rather than Pixiv PIDs.
    Keep the metadata limited to actual Pixiv records so those images are not
    presented with misleading source information.
    """

    source_type = getattr(illust, "source_type", None)
    if source_type not in (None, "pixiv"):
        return []
    return [f"PID: {illust.id}", f"图片链接: {image_link}"]


def _caption(illust: Illustration, page: int, *, image_link: str | None = None) -> str:
    lines = [
        f"标题: {illust.title or illust.id}",
        f"作者: {illust.author_name or '未知'} (Pixiv {illust.author_id})",
        f"页码: {page + 1}/{illust.page_count}",
        f"AI 作品: {'是' if illust.is_ai else '否'}",
    ]
    if image_link:
        lines.extend(_pixiv_metadata_lines(illust, image_link))
    return "\n".join(lines)


def _with_pixiv_metadata(
    caption: str, illust: Illustration, image_link: str
) -> str:
    metadata = _pixiv_metadata_lines(illust, image_link)
    if not metadata:
        return caption
    return "\n".join([caption, *metadata])


async def send_illustration_photo(
    bot: Any,
    group_id: int,
    illust: Illustration,
    page: int,
    *,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    reply_markup: Any | None = None,
):
    """Send one page and persist the Telegram compressed photo file id."""

    resource = resource_for_illustration(illust, page)
    message_caption = (
        _caption(illust, page, image_link=resource.link)
        if caption is None
        else _with_pixiv_metadata(caption, illust, resource.link)
    )
    kwargs: dict[str, Any] = {
        "chat_id": group_id,
        "caption": message_caption,
    }
    if reply_to_message_id is not None:
        kwargs["reply_to_message_id"] = reply_to_message_id
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    if resource.file_id:
        try:
            return await bot.send_photo(photo=resource.file_id, **kwargs)
        except (TimedOut, RetryAfter, NetworkError):
            raise
        except TelegramError:
            ids = ensure_list_length(getattr(illust, "compressed_file_ids", None), illust.page_count)
            if ids[page] == resource.file_id:
                ids[page] = None
                illust.compressed_file_ids = ids
                await illust_registry.save_illustration(illust)
    file_bytes = await resource.fetcher(resource.filename, resource.link)
    file_urls = ensure_list_length(getattr(illust, "file_urls", None), illust.page_count)
    if not file_urls[page]:
        storage = await use_storage()
        if storage is not None:
            try:
                file_urls[page] = await storage.upload(
                    file_bytes,
                    resource.filename,
                    sub_folder=storage.join_path(
                        "manual" if getattr(illust, "source_type", "pixiv") == "manual" else "pixiv",
                        str(illust.id),
                    ),
                )
                illust.file_urls = file_urls
                await illust_registry.save_illustration(illust)
            except Exception:
                logger.exception("Failed to persist storage URL for illustration %s", illust.id)
    stream = BytesIO(file_bytes)
    stream.name = resource.filename
    message = await bot.send_photo(photo=stream, **kwargs)
    photo_sizes = getattr(message, "photo", None) or []
    if photo_sizes:
        cached_id = getattr(photo_sizes[-1], "file_id", None)
        if cached_id:
            ids = ensure_list_length(getattr(illust, "compressed_file_ids", None), illust.page_count)
            ids[page] = cached_id
            illust.compressed_file_ids = ids
            await illust_registry.save_illustration(illust)
    return message


class ImagePushWorker:
    def __init__(self, bot: Any):
        self.bot = bot
        self.runner: asyncio.Task | None = None
        # Keep import locks process-wide so separate worker instances cannot
        # download and persist the same missing PID concurrently.
        self.pid_locks = _PID_IMPORT_LOCKS
        self.batch_lock = asyncio.Lock()

    async def start(self) -> None:
        if self.runner is not None:
            return
        await self.recover()
        self.runner = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.runner is None:
            return
        self.runner.cancel()
        await asyncio.gather(self.runner, return_exceptions=True)
        self.runner = None
        # A cancellation may have interrupted a Telegram request. Preserve
        # the conservative no-resend guarantee even on a clean shutdown or
        # bot reconfiguration.
        await self.recover()

    async def recover(self) -> None:
        """Mark in-flight sends uncertain; never replay an ambiguous send."""

        async with engine.new_session() as session:
            batches = (
                await session.scalars(
                    select(ImagePushBatch).where(ImagePushBatch.state == "running")
                )
            ).all()
            for batch in batches:
                batch.state = "uncertain"
                batch.result = "进程中断，结果需核查"
                batch.completed_at = None
            running_batch_ids = [batch.id for batch in batches]
            deliveries_rows = (
                await session.scalars(
                    select(ImagePushDelivery).where(
                        ImagePushDelivery.batch_id.in_(running_batch_ids or [""]),
                        ImagePushDelivery.state.in_(["pending", "running"])
                    )
                )
            ).all()
            for delivery in deliveries_rows:
                delivery.state = "uncertain"
                delivery.reason = "进程中断，批次结果需人工核查"
                delivery.completed_at = None
            await session.commit()

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Image push worker tick failed")
            await asyncio.sleep(1)

    async def tick(self) -> None:
        await self._schedule_due_plans()
        async with self.batch_lock:
            batch_id = await self._claim_batch()
            if batch_id:
                try:
                    await self._dispatch_batch(batch_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Image push batch %s failed unexpectedly", batch_id)
                    await self._mark_batch_failed(
                        batch_id, str(exc) or type(exc).__name__
                    )

    async def _schedule_due_plans(self) -> None:
        clock = now()
        async with engine.new_session() as session:
            plans = (
                await session.scalars(
                    select(ImagePushPlan)
                    .where(ImagePushPlan.enabled.is_(True), ImagePushPlan.next_run_at <= clock)
                    .order_by(ImagePushPlan.next_run_at, ImagePushPlan.id)
                    .limit(20)
                )
            ).all()
            for plan in plans:
                snapshot = {
                    "target_scope": plan.target_scope,
                    "group_ids": list(plan.group_ids or []),
                    "mode": plan.mode,
                    "pid": plan.pid,
                    "pid_by_group": plan.pid_by_group,
                }
                session.add(
                    ImagePushBatch(
                        id=uid(),
                        plan_id=plan.id,
                        trigger="auto",
                        state="pending",
                        due_at=plan.next_run_at,
                        config_snapshot=_config_snapshot(snapshot),
                        summary={},
                        created_at=now(),
                    )
                )
                if plan.repeat == "once":
                    plan.enabled = False
                else:
                    plan.next_run_at = next_occurrence(
                        plan.next_run_at,
                        plan.repeat,
                        plan.timezone,
                        interval_seconds=plan.interval_seconds,
                        clock=clock,
                    )
            await session.commit()

    async def _claim_batch(self) -> str | None:
        async with engine.new_session() as session:
            batch = await session.scalar(
                select(ImagePushBatch)
                .where(ImagePushBatch.state == "pending")
                # Manual and scheduled batches share one FIFO queue. The
                # creation timestamp, rather than the scheduled due time,
                # determines which batch gets the bot next.
                .order_by(ImagePushBatch.created_at, ImagePushBatch.id)
                .limit(1)
            )
            if batch is None or batch.due_at > now():
                return None
            batch_id = batch.id
            result = await session.execute(
                update(ImagePushBatch)
                .where(ImagePushBatch.id == batch_id, ImagePushBatch.state == "pending")
                .values(state="running", started_at=now(), completed_at=None)
            )
            await session.commit()
            return batch_id if result.rowcount else None

    async def _dispatch_batch(self, batch_id: str) -> None:
        batch = await get_batch(batch_id)
        if batch is None or batch.state != "running":
            return
        rows = await deliveries(batch_id)
        if not rows:
            try:
                await self._prepare_deliveries(batch)
            except Exception as exc:
                logger.exception("Failed to prepare image push batch %s", batch_id)
                await self._mark_batch_failed(batch_id, str(exc) or type(exc).__name__)
                return
            rows = await deliveries(batch_id)

        # RetryAfter may leave a delivery pending until its server-provided time.
        future = [
            row.next_attempt_at
            for row in rows
            if row.state == "pending" and row.next_attempt_at and row.next_attempt_at > now()
        ]
        if future:
            async with engine.new_session() as session:
                await session.execute(
                    update(ImagePushBatch)
                    .where(ImagePushBatch.id == batch_id, ImagePushBatch.state == "running")
                    .values(state="pending", due_at=min(future), started_at=None)
                )
                await session.commit()
            return

        for row in rows:
            if row.state != "pending":
                continue
            outcome = await self._send_delivery(row.id)
            if outcome == "retry":
                break
        await self._finalize_batch(batch_id)

    async def _mark_batch_failed(self, batch_id: str, reason: str) -> None:
        completed = now()
        async with engine.new_session() as session:
            delivery_result = await session.execute(
                update(ImagePushDelivery)
                .where(
                    ImagePushDelivery.batch_id == batch_id,
                    ImagePushDelivery.state.in_(["pending", "running"]),
                )
                .values(state="failed", reason=reason, completed_at=completed)
            )
            failed_count = int(delivery_result.rowcount or 0)
            total_count = max(failed_count, 1)
            await session.execute(
                update(ImagePushBatch)
                .where(ImagePushBatch.id == batch_id, ImagePushBatch.state == "running")
                .values(
                    state="failed",
                    summary={
                        "total": total_count,
                        "success": 0,
                        "skipped": 0,
                        "failed": failed_count or 1,
                        "uncertain": 0,
                    },
                    result=reason,
                    completed_at=completed,
                )
            )
            await session.commit()

    async def _prepare_deliveries(self, batch: ImagePushBatch) -> None:
        config = dict(batch.config_snapshot or {})
        requested_ids = [int(value) for value in (config.get("group_ids") or [])]
        if config.get("target_scope") == "all":
            async with engine.new_session() as session:
                groups = list((await session.scalars(select(Group).order_by(Group.id))).all())
        else:
            async with engine.new_session() as session:
                found = list((await session.scalars(select(Group).where(Group.id.in_(requested_ids)))).all()) if requested_ids else []
            by_id = {int(group.id): group for group in found}
            groups = [by_id.get(group_id) for group_id in requested_ids]

        group_by_id = {int(group.id): group for group in groups if group is not None}
        target_ids = requested_ids if config.get("target_scope") != "all" else sorted(group_by_id)
        # For selected groups that were deleted, retain a delivery row so the
        # final report remains complete.
        for group_id in target_ids:
            group = group_by_id.get(group_id)
            reason = _group_block_reason(group)
            if reason is None:
                can_send, permission_reason = await _bot_can_send_photo(self.bot, group_id)
                if not can_send:
                    reason = permission_reason
            state = "skipped" if reason else "pending"
            async with engine.new_session() as session:
                existing = await session.scalar(
                    select(ImagePushDelivery).where(
                        ImagePushDelivery.batch_id == batch.id,
                        ImagePushDelivery.group_id == group_id,
                    )
                )
                if existing is None:
                    session.add(
                        ImagePushDelivery(
                            id=uid(), batch_id=batch.id, group_id=group_id,
                            state=state, reason=reason, created_at=now(),
                        )
                    )
                await session.commit()

        rows = await deliveries(batch.id)
        eligible = [row for row in rows if row.state == "pending"]
        mode = config.get("mode")
        if mode == "fixed_different":
            mapping = {str(key): value for key, value in (config.get("pid_by_group") or {}).items()}
            # Resolve each PID specification once per batch. Besides making
            # omitted-page selection deterministic for groups sharing a PID,
            # this prevents a failed import from being retried repeatedly for
            # every mapped group in the same batch.
            resolved: dict[str, tuple[int, int] | Exception] = {}
            for row in eligible:
                spec = mapping.get(str(row.group_id))
                if not spec:
                    logger.warning(
                        "Image push batch %s has no PID mapping for group %s; skipping",
                        batch.id,
                        row.group_id,
                    )
                    await self._set_delivery(row.id, "skipped", "未提供该群的 PID 映射")
                    continue
                if spec not in resolved:
                    try:
                        pid, requested_page = parse_pid_spec(spec)
                        illust = await _ensure_illustration(pid, self.pid_locks)
                        resolved[spec] = (pid, _page_index(illust, requested_page))
                    except Exception as exc:
                        resolved[spec] = exc
                result = resolved[spec]
                if isinstance(result, Exception):
                    await self._set_delivery(row.id, "failed", str(result) or type(result).__name__)
                else:
                    pid, page = result
                    await self._set_delivery(
                        row.id, "pending", None, pixiv_id=str(pid), page=page
                    )
        elif mode == "fixed_same":
            spec = config.get("pid")
            if not spec:
                for row in eligible:
                    await self._set_delivery(row.id, "failed", "未提供 PID")
            else:
                try:
                    pid, requested_page = parse_pid_spec(spec)
                    illust = await _ensure_illustration(pid, self.pid_locks)
                    page = _page_index(illust, requested_page)
                    for row in eligible:
                        await self._set_delivery(row.id, "pending", None, pixiv_id=str(pid), page=page)
                except Exception as exc:
                    for row in eligible:
                        await self._set_delivery(row.id, "failed", str(exc))
        elif mode == "random_same":
            if not eligible:
                return
            groups_ok = [group_by_id[row.group_id] for row in eligible if row.group_id in group_by_id]
            if not groups_ok:
                return
            try:
                illust = await _random_illustration(
                    min(int(group.sanity_limit) for group in groups_ok),
                    all(bool(group.allow_r18g) for group in groups_ok),
                )
            except Exception as exc:
                for row in eligible:
                    await self._set_delivery(row.id, "failed", str(exc) or type(exc).__name__)
                return
            if illust is None:
                for row in eligible:
                    await self._set_delivery(row.id, "failed", "没有符合所有目标群限制的图片")
            else:
                try:
                    page = _page_index(illust, None)
                except Exception as exc:
                    for row in eligible:
                        await self._set_delivery(row.id, "failed", str(exc) or type(exc).__name__)
                    return
                for row in eligible:
                    await self._set_delivery(row.id, "pending", None, pixiv_id=str(illust.id), page=page)
        elif mode == "random_different":
            for row in eligible:
                group = group_by_id.get(row.group_id)
                if group is None:
                    await self._set_delivery(row.id, "skipped", "群组不存在或已删除")
                    continue
                try:
                    illust = await _random_illustration(int(group.sanity_limit), bool(group.allow_r18g))
                except Exception as exc:
                    await self._set_delivery(row.id, "failed", str(exc) or type(exc).__name__)
                    continue
                if illust is None:
                    await self._set_delivery(row.id, "failed", "没有符合该群限制的图片")
                    continue
                try:
                    page = _page_index(illust, None)
                except Exception as exc:
                    await self._set_delivery(row.id, "failed", str(exc) or type(exc).__name__)
                    continue
                await self._set_delivery(row.id, "pending", None, pixiv_id=str(illust.id), page=page)
        else:
            for row in eligible:
                await self._set_delivery(row.id, "failed", "不支持的图片分配模式")

    async def _resolve_fixed_delivery(self, delivery_id: str, spec: str) -> None:
        try:
            pid, requested_page = parse_pid_spec(spec)
            illust = await _ensure_illustration(pid, self.pid_locks)
            page = _page_index(illust, requested_page)
        except Exception as exc:
            await self._set_delivery(delivery_id, "failed", str(exc))
            return
        await self._set_delivery(delivery_id, "pending", None, pixiv_id=str(pid), page=page)

    async def _set_delivery(
        self, delivery_id: str, state: str, reason: str | None = None,
        *, pixiv_id: str | None = None, page: int | None = None,
    ) -> None:
        async with engine.new_session() as session:
            row = await session.get(ImagePushDelivery, delivery_id)
            if row is None:
                return
            row.state = state
            row.reason = reason
            if pixiv_id is not None:
                row.pixiv_id = pixiv_id
            if page is not None:
                row.page = page
            if state in {"skipped", "failed"}:
                row.completed_at = now()
            await session.commit()

    async def _send_delivery(self, delivery_id: str) -> str:
        async with engine.new_session() as session:
            row = await session.get(ImagePushDelivery, delivery_id)
            if row is None or row.state != "pending":
                return "done"
            row.state = "running"
            row.attempts += 1
            row.started_at = now()
            group_id, pixiv_id, page, attempts = row.group_id, row.pixiv_id, row.page, row.attempts
            await session.commit()
        try:
            if not pixiv_id or page is None:
                raise RuntimeError("没有解析出可发送的图片")
            # Random mode may select a manually uploaded illustration whose
            # catalogue key is not numeric; the registry query accepts both.
            lookup_id: int | str = int(pixiv_id) if pixiv_id.isdigit() else pixiv_id
            illust = await illust_registry.get_illust_info(lookup_id)
            if illust is None:
                raise RuntimeError("图片记录已不存在")
            policy_reason = await _image_policy_reason(group_id, illust)
            if policy_reason:
                await self._set_delivery(delivery_id, "skipped", policy_reason)
                return "done"
            message = await send_illustration_photo(self.bot, group_id, illust, page)
        except RetryAfter as exc:
            if attempts < 3:
                retry_after = exc.retry_after
                delay = (
                    retry_after.total_seconds()
                    if isinstance(retry_after, timedelta)
                    else float(retry_after)
                )
                async with engine.new_session() as session:
                    row = await session.get(ImagePushDelivery, delivery_id)
                    row.state = "pending"
                    row.next_attempt_at = now() + timedelta(seconds=max(1, int(delay)))
                    row.reason = f"Telegram 限流，等待后重试（第 {attempts} 次）"
                    row.started_at = None
                    await session.commit()
                return "retry"
            await self._set_delivery(delivery_id, "failed", "Telegram 限流重试次数已用尽")
            return "done"
        except TimedOut:
            await self._set_delivery(delivery_id, "uncertain", "Telegram 请求超时，图片是否送达需人工核查")
            return "done"
        except NetworkError:
            await self._set_delivery(delivery_id, "uncertain", "Telegram 连接异常，图片是否送达需人工核查")
            return "done"
        except (TimeoutError, ConnectionError):
            await self._set_delivery(delivery_id, "uncertain", "连接或请求超时，图片是否送达需人工核查")
            return "done"
        except TelegramError as exc:
            await self._set_delivery(delivery_id, "failed", type(exc).__name__)
            return "done"
        except Exception as exc:
            logger.exception("Image push delivery failed for group %s", group_id)
            await self._set_delivery(delivery_id, "failed", str(exc) or type(exc).__name__)
            return "done"
        async with engine.new_session() as session:
            row = await session.get(ImagePushDelivery, delivery_id)
            row.state = "success"
            row.telegram_message_id = getattr(message, "message_id", None)
            row.reason = None
            row.completed_at = now()
            await session.commit()
        return "done"

    async def _finalize_batch(self, batch_id: str) -> None:
        rows = await deliveries(batch_id)
        if any(row.state in {"pending", "running"} for row in rows):
            retry_times = [
                row.next_attempt_at
                for row in rows
                if row.state == "pending" and row.next_attempt_at is not None
            ]
            async with engine.new_session() as session:
                await session.execute(
                    update(ImagePushBatch)
                    .where(ImagePushBatch.id == batch_id, ImagePushBatch.state == "running")
                    .values(
                        state="pending",
                        due_at=min(retry_times) if retry_times else now(),
                        started_at=None,
                    )
                )
                await session.commit()
            return
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.state] = counts.get(row.state, 0) + 1
        if not rows or counts.get("skipped", 0) == len(rows):
            state = "skipped"
        elif counts.get("uncertain"):
            state = "uncertain"
        elif counts.get("success") and counts.get("success") != len(rows):
            state = "partial"
        elif counts.get("failed") and not counts.get("success"):
            state = "failed"
        else:
            state = "success"
        async with engine.new_session() as session:
            summary = {
                "total": len(rows),
                "success": counts.get("success", 0),
                "skipped": counts.get("skipped", 0),
                "failed": counts.get("failed", 0),
                "uncertain": counts.get("uncertain", 0),
            }
            await session.execute(
                update(ImagePushBatch)
                .where(ImagePushBatch.id == batch_id, ImagePushBatch.state == "running")
                .values(
                    state=state,
                    summary=summary,
                    result="；".join(f"{key}: {value}" for key, value in sorted(counts.items())),
                    completed_at=now(),
                )
            )
            await session.commit()


async def trigger_plan(plan_id: str) -> ImagePushBatch | None:
    plan = await get_plan(plan_id)
    if plan is None:
        return None
    return await create_batch_from_plan(plan_id, trigger="manual", due_at=now())


async def can_use_push_command(user_id: int | None) -> bool:
    return await has_super_user_access(user_id)
