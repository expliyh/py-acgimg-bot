"""Background executor for illustration import tasks.

Each import runs as an asyncio task so the admin console can poll progress
(page x / y) and keep a persisted history of past imports.
"""

from __future__ import annotations

import asyncio
import copy
import contextvars
import logging
import weakref
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Illustration, IllustrationImportTask
from registries import illust_registry
from registries.engine import engine

from .illustration_importer import import_illustration
from .illustration_fields import EDITABLE_ILLUSTRATION_FIELDS
from .illustration_media import delete_media_url

logger = logging.getLogger(__name__)

# Keep strong references to running background tasks so they are not GC'd.
_background_tasks: set[asyncio.Task] = set()
# A lock per event loop keeps imports (including batch refreshes) serial while
# avoiding cross-loop asyncio.Lock errors in the test suite.
_import_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)
_enqueue_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)
_enqueue_lock_held: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "illustration_enqueue_lock_held", default=False
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _update_task(task_id: int, **values: Any) -> IllustrationImportTask | None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        task = await session.get(IllustrationImportTask, task_id)
        if task is None:
            return None
        for key, value in values.items():
            setattr(task, key, value)
        await session.commit()
        await session.refresh(task)
        return task


async def create_import_task(
    pixiv_id: int,
    overrides: dict[str, Any] | None,
) -> IllustrationImportTask:
    """Persist a pending import task and launch it in the background."""
    async with _enqueue_scope():
        tasks = await _persist_import_tasks([(pixiv_id, overrides)])
        task = tasks[0]
        _schedule_background(_run_import_task(task.id))
        return task


def _schedule_background(coroutine) -> None:
    loop = asyncio.get_running_loop()
    bg_task = loop.create_task(coroutine)
    _background_tasks.add(bg_task)
    bg_task.add_done_callback(_background_tasks.discard)


async def _persist_import_tasks(
    items: list[tuple[int, dict[str, Any] | None]],
) -> list[IllustrationImportTask]:
    if not items:
        return []
    async with engine.new_session() as session:
        session: AsyncSession = session
        tasks: list[IllustrationImportTask] = []
        for pixiv_id, overrides in items:
            task = IllustrationImportTask(
                pixiv_id=str(pixiv_id),
                title=(overrides or {}).get("title"),
                status="pending",
                overrides=overrides or None,
            )
            session.add(task)
            tasks.append(task)
        await session.commit()
        for task in tasks:
            await session.refresh(task)
        return tasks


async def create_import_tasks(
    items: list[tuple[int, dict[str, Any] | None]],
) -> list[IllustrationImportTask]:
    """Persist several pending tasks and execute them in one serial batch."""

    if not items:
        return []
    async with _enqueue_scope():
        tasks = await _persist_import_tasks(items)
        _schedule_background(_run_import_batch([task.id for task in tasks]))
        return tasks


async def create_refresh_tasks(illustration_ids: list[str]) -> list[IllustrationImportTask]:
    """Snapshot local metadata and enqueue Pixiv refreshes as one batch."""

    normalized_ids = list(dict.fromkeys(str(item).strip() for item in illustration_ids if str(item).strip()))
    if not normalized_ids:
        raise ValueError("至少选择一张图片")
    if len(normalized_ids) > 100:
        raise ValueError("一次最多刷新 100 张图片")

    async with _enqueue_scope():
        async with engine.new_session() as session:
            session: AsyncSession = session
            rows = list(
                (
                    await session.scalars(
                        select(Illustration).where(Illustration.id.in_(normalized_ids))
                    )
                ).all()
            )
            found = {str(row.id): row for row in rows}
            missing = [item for item in normalized_ids if item not in found]
            if missing:
                raise LookupError(f"插画不存在：{', '.join(missing)}")
            # Rows created before ``source_type`` was introduced are treated as
            # Pixiv records for refresh compatibility; only an explicit manual
            # marker is rejected.
            manual = [
                item
                for item in normalized_ids
                if (
                    item.lower().startswith("manual_")
                    or (
                        getattr(found[item], "source_type", None) is not None
                        and str(getattr(found[item], "source_type", "")).strip().lower()
                        != "pixiv"
                    )
                )
            ]
            if manual:
                raise ValueError(f"仅 Pixiv 插画支持刷新：{', '.join(manual)}")
            active = list(
                (
                    await session.scalars(
                        select(IllustrationImportTask.pixiv_id).where(
                            IllustrationImportTask.status.in_(["pending", "running"]),
                            IllustrationImportTask.pixiv_id.in_(normalized_ids),
                        )
                    )
                ).all()
            )
            if active:
                active_ids = {str(item) for item in active}
                ordered_active = [item for item in normalized_ids if item in active_ids]
                raise RuntimeError(f"以下插画已有进行中的任务：{', '.join(ordered_active)}")

            items: list[tuple[int, dict[str, Any]]] = []
            for illustration_id in normalized_ids:
                row = found[illustration_id]
                if (
                    not illustration_id.isascii()
                    or not illustration_id.isdigit()
                    or illustration_id.startswith("0")
                ):
                    raise ValueError(f"Pixiv ID 无效：{illustration_id}")
                # Preserve the database values exactly.  Normalizing a refresh
                # snapshot (for example trimming a title or truncating tags) would
                # unexpectedly edit local metadata even though the user only
                # requested fresh Pixiv source data and files.
                snapshot = {
                    field: copy.deepcopy(getattr(row, field, None))
                    for field in EDITABLE_ILLUSTRATION_FIELDS
                }
                snapshot["__gallery_refresh__"] = True
                items.append((int(illustration_id), snapshot))

        # Keep the public helper as the single task-creation seam.  The
        # re-entrant enqueue scope below avoids taking the same asyncio lock
        # twice while preserving atomic validation + persistence.
        return await create_import_tasks(items)


@asynccontextmanager
async def _enqueue_scope():
    if _enqueue_lock_held.get():
        yield
        return
    async with _lock_for_current_loop(_enqueue_locks):
        token = _enqueue_lock_held.set(True)
        try:
            yield
        finally:
            _enqueue_lock_held.reset(token)


def _lock_for_current_loop(
    locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock],
) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        locks[loop] = lock
    return lock


def _file_urls(value: object) -> set[str]:
    if isinstance(value, list):
        return {item.strip() for item in value if isinstance(item, str) and item.strip()}
    if isinstance(value, str) and value.strip():
        return {value.strip()}
    return set()


async def _old_file_urls(illustration_id: str) -> set[str]:
    async with engine.new_session() as session:
        session: AsyncSession = session
        row = await session.get(Illustration, str(illustration_id))
        return _file_urls(row.file_urls if row is not None else None)


async def _cleanup_stale_files(illustration_id: str, old_urls: set[str], new_urls: set[str]) -> None:
    stale = old_urls - new_urls
    if not stale:
        return
    async with engine.new_session() as session:
        session: AsyncSession = session
        remaining_rows = list(
            (
                await session.scalars(
                    select(Illustration).where(Illustration.id != str(illustration_id))
                )
            ).all()
        )
    referenced = set().union(*(_file_urls(row.file_urls) for row in remaining_rows)) if remaining_rows else set()
    for url in stale - referenced:
        try:
            await delete_media_url(url)
        except FileNotFoundError:
            # A missing stale object is already cleaned up.
            continue
        except Exception as exc:  # stale-file cleanup must not fail the refresh
            logger.warning("Failed to clean stale illustration file %s: %s", url, exc)


async def _run_import_task(task_id: int) -> None:
    async with _lock_for_current_loop(_import_locks):
        await _run_import_task_locked(task_id)


async def _run_import_batch(task_ids: list[int]) -> None:
    async with _lock_for_current_loop(_import_locks):
        for task_id in task_ids:
            await _run_import_task_locked(task_id)


async def _run_import_task_locked(task_id: int) -> None:
    task = await _update_task(task_id, status="running", current_page=0)
    if task is None:
        return

    try:
        overrides = dict(task.overrides or {})
        gallery_refresh = bool(overrides.pop("__gallery_refresh__", False))
        old_urls = await _old_file_urls(task.pixiv_id)

        async def _on_page_done(page: int) -> None:
            await _update_task(task_id, current_page=page)

        result = await import_illustration(
            int(task.pixiv_id),
            bot=None,
            telegram_chat_ids=None,
            on_page_done=_on_page_done,
        )

        saved = result.illustration
        if gallery_refresh and str(saved.id) != str(task.pixiv_id):
            raise RuntimeError(
                f"Pixiv 刷新返回了不匹配的插画 ID：{saved.id}（请求 {task.pixiv_id}）"
            )
        if gallery_refresh:
            # A refreshed file must never reuse a Telegram cache entry created
            # for the previous bytes.  The next send will populate it again.
            saved.compressed_file_ids = [None] * int(saved.page_count or 0)
            saved.original_file_ids = [None] * int(saved.page_count or 0)
            for field in EDITABLE_ILLUSTRATION_FIELDS:
                if field in overrides:
                    setattr(saved, field, copy.deepcopy(overrides[field]))
            saved = await illust_registry.save_illustration(saved)
        elif overrides:
            # Keep the established /import contract: null means "use the
            # value from Pixiv", while an explicitly supplied non-null value
            # overrides it.  Gallery refresh snapshots use the branch above
            # because null is a meaningful local value there.
            for field in ("title", "caption", "tags", "sanity_level", "r18g", "is_ai"):
                value = overrides.get(field)
                if value is not None:
                    setattr(saved, field, value)
            saved = await illust_registry.save_illustration(saved)

        await _cleanup_stale_files(task.pixiv_id, old_urls, _file_urls(saved.file_urls))

        def _cache_id_for_result(
            values: object, page_index: int, original: str | None
        ) -> str | None:
            if not gallery_refresh:
                return original
            if isinstance(values, list) and page_index < len(values):
                value = values[page_index]
                return value if isinstance(value, str) else None
            return None

        result_payload: dict[str, Any] = {
            "id": saved.id,
            "title": saved.title,
            "author_id": saved.author_id,
            "author_name": saved.author_name,
            "page_count": saved.page_count,
            "created": result.created,
            "telegram_cache_enabled": result.telegram_cache_enabled,
            "pages": [
                {
                    "index": page.index,
                    "storage_url": page.storage_url,
                    # A gallery refresh deliberately invalidates the persisted
                    # Telegram IDs; report those cleared values.  Keep the
                    # established /import task contract for ordinary imports,
                    # where the importer result is the source of page IDs.
                    "compressed_file_id": _cache_id_for_result(
                        saved.compressed_file_ids, page.index, page.compressed_file_id
                    ),
                    "original_file_id": _cache_id_for_result(
                        saved.original_file_ids, page.index, page.original_file_id
                    ),
                }
                for page in result.pages
            ],
        }
        await _update_task(
            task_id,
            status="success",
            created=result.created,
            total_pages=saved.page_count,
            current_page=saved.page_count,
            result=result_payload,
            finished_at=_now(),
        )
        logger.info("Import task %s finished: Pixiv %s (%s)", task_id, saved.id, "created" if result.created else "updated")
    except Exception as exc:  # noqa: BLE001 - 任务失败要落库并继续
        logger.exception("Import task %s failed", task_id)
        await _update_task(
            task_id,
            status="failed",
            error_message=str(exc) or exc.__class__.__name__,
            finished_at=_now(),
        )


async def list_import_tasks(
    *,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> tuple[int, list[IllustrationImportTask]]:
    async with engine.new_session() as session:
        session: AsyncSession = session
        sort_column = getattr(IllustrationImportTask, sort_by)
        stmt = select(IllustrationImportTask)
        count_stmt = select(func.count()).select_from(IllustrationImportTask)
        if status is not None:
            stmt = stmt.where(IllustrationImportTask.status == status)
            count_stmt = count_stmt.where(IllustrationImportTask.status == status)
        ordering = desc(sort_column) if sort_order == "desc" else asc(sort_column)
        result = await session.execute(
            stmt.order_by(ordering, IllustrationImportTask.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = (await session.execute(count_stmt)).scalar_one()
        return total, list(result.scalars())


async def get_import_task(task_id: int) -> IllustrationImportTask | None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        return await session.get(IllustrationImportTask, task_id)
