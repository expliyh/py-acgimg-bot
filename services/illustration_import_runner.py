"""Background executor for illustration import tasks.

Each import runs as an asyncio task so the admin console can poll progress
(page x / y) and keep a persisted history of past imports.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import IllustrationImportTask
from registries import illust_registry
from registries.engine import engine

from .illustration_importer import import_illustration

logger = logging.getLogger(__name__)

# Keep strong references to running background tasks so they are not GC'd.
_background_tasks: set[asyncio.Task] = set()


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
    async with engine.new_session() as session:
        session: AsyncSession = session
        task = IllustrationImportTask(
            pixiv_id=str(pixiv_id),
            title=(overrides or {}).get("title"),
            status="pending",
            overrides=overrides or None,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    loop = asyncio.get_running_loop()
    bg_task = loop.create_task(_run_import_task(task_id))
    _background_tasks.add(bg_task)
    bg_task.add_done_callback(_background_tasks.discard)
    return task


async def _run_import_task(task_id: int) -> None:
    task = await _update_task(task_id, status="running", current_page=0)
    if task is None:
        return

    try:
        overrides = dict(task.overrides or {})

        async def _on_page_done(page: int) -> None:
            await _update_task(task_id, current_page=page)

        result = await import_illustration(
            int(task.pixiv_id),
            bot=None,
            telegram_chat_ids=None,
            on_page_done=_on_page_done,
        )

        saved = result.illustration
        if overrides:
            if overrides.get("title") is not None:
                saved.title = overrides["title"]
            if overrides.get("caption") is not None:
                saved.caption = overrides["caption"]
            if overrides.get("tags") is not None:
                saved.tags = overrides["tags"]
            if overrides.get("sanity_level") is not None:
                saved.sanity_level = overrides["sanity_level"]
            if overrides.get("r18g") is not None:
                saved.r18g = overrides["r18g"]
            if overrides.get("is_ai") is not None:
                saved.is_ai = overrides["is_ai"]
            saved = await illust_registry.save_illustration(saved)

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
                    "compressed_file_id": page.compressed_file_id,
                    "original_file_id": page.original_file_id,
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
