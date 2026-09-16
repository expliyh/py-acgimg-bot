"""Database operations shared by the illustration gallery API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from sqlalchemy import String, asc, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Illustration, IllustrationImportTask
from registries.engine import engine

from .illustration_fields import normalize_edit_values
from .illustration_media import delete_media_url


logger = logging.getLogger(__name__)


class IllustrationNotFoundError(LookupError):
    def __init__(self, illustration_ids: list[str] | str):
        if isinstance(illustration_ids, str):
            illustration_ids = [illustration_ids]
        self.ids = illustration_ids
        super().__init__(f"插画不存在：{', '.join(illustration_ids)}")


class IllustrationBusyError(RuntimeError):
    def __init__(self, illustration_ids: list[str]):
        self.ids = illustration_ids
        super().__init__(f"以下插画正在导入或刷新：{', '.join(illustration_ids)}")


SORT_COLUMNS = {
    "id": Illustration.id,
    "title": Illustration.title,
    "author_name": Illustration.author_name,
    "page_count": Illustration.page_count,
    "sanity_level": Illustration.sanity_level,
    "x_restrict": Illustration.x_restrict,
    "source_type": Illustration.source_type,
}
_NON_NULL_EDIT_FIELDS = {"sanity_level", "x_restrict", "r18g", "is_ai"}


def _urls(value: object) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _indexed_urls(value: object) -> list[tuple[int, str]]:
    if isinstance(value, list):
        return [
            (page, item.strip())
            for page, item in enumerate(value)
            if isinstance(item, str) and item.strip()
        ]
    if isinstance(value, str) and value.strip():
        return [(0, value.strip())]
    return []


def _apply_filters(
    stmt,
    *,
    q: str | None,
    source_type: str | None,
    r18g: bool | None,
    is_ai: bool | None,
    x_restrict: int | None,
    sanity_min: int | None,
    sanity_max: int | None,
):
    if q:
        term = f"%{q.strip()}%"
        # JSON is stored as text on SQLite and as JSON on MariaDB.  Casting to
        # String keeps the same broad search semantics on both backends.
        searchable_tags = cast(Illustration.tags, String)
        stmt = stmt.where(
            or_(
                Illustration.id.ilike(term),
                Illustration.title.ilike(term),
                Illustration.author_id.ilike(term),
                Illustration.author_name.ilike(term),
                Illustration.caption.ilike(term),
                searchable_tags.ilike(term),
            )
        )
    if source_type is not None:
        if source_type == "pixiv":
            stmt = stmt.where(
                or_(Illustration.source_type == "pixiv", Illustration.source_type.is_(None))
            )
        else:
            stmt = stmt.where(Illustration.source_type == source_type)
    if r18g is not None:
        stmt = stmt.where(Illustration.r18g.is_(r18g))
    if is_ai is not None:
        stmt = stmt.where(Illustration.is_ai.is_(is_ai))
    if x_restrict is not None:
        stmt = stmt.where(Illustration.x_restrict == x_restrict)
    if sanity_min is not None:
        stmt = stmt.where(Illustration.sanity_level >= sanity_min)
    if sanity_max is not None:
        stmt = stmt.where(Illustration.sanity_level <= sanity_max)
    return stmt


def _validated_edit_values(values: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_edit_values(values)
    if not normalized:
        raise ValueError("至少提供一个需要修改的字段")
    for field in _NON_NULL_EDIT_FIELDS:
        if field not in normalized:
            continue
        value = normalized[field]
        if value is None:
            raise ValueError(f"{field} 不能为空")
        if field == "sanity_level" and (
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10
        ):
            raise ValueError("过滤等级必须是 0 到 10 的整数")
        if field == "x_restrict" and (
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2
        ):
            raise ValueError("x_restrict 必须是 0 到 2 的整数")
        if field in {"r18g", "is_ai"} and not isinstance(value, bool):
            raise ValueError(f"{field} 必须是布尔值")
    return normalized


async def list_illustrations(
    *,
    limit: int,
    offset: int,
    q: str | None = None,
    source_type: str | None = None,
    r18g: bool | None = None,
    is_ai: bool | None = None,
    x_restrict: int | None = None,
    sanity_min: int | None = None,
    sanity_max: int | None = None,
    sort_by: str = "id",
    sort_order: str = "desc",
) -> tuple[int, list[Illustration]]:
    if limit < 1 or limit > 100 or offset < 0:
        raise ValueError("分页参数超出范围")
    if sanity_min is not None and sanity_max is not None and sanity_min > sanity_max:
        raise ValueError("分级范围无效：最小值不能大于最大值")
    if sort_by not in SORT_COLUMNS:
        raise ValueError(f"不支持的排序字段: {sort_by}")
    if sort_order not in {"asc", "desc"}:
        raise ValueError(f"不支持的排序方向: {sort_order}")

    async with engine.new_session() as session:
        session: AsyncSession = session
        stmt = _apply_filters(
            select(Illustration),
            q=q,
            source_type=source_type,
            r18g=r18g,
            is_ai=is_ai,
            x_restrict=x_restrict,
            sanity_min=sanity_min,
            sanity_max=sanity_max,
        )
        count_stmt = _apply_filters(
            select(func.count()).select_from(Illustration),
            q=q,
            source_type=source_type,
            r18g=r18g,
            is_ai=is_ai,
            x_restrict=x_restrict,
            sanity_min=sanity_min,
            sanity_max=sanity_max,
        )
        column = SORT_COLUMNS[sort_by]
        ordering = desc(column) if sort_order == "desc" else asc(column)
        result = await session.execute(
            stmt.order_by(ordering, desc(Illustration.id)).limit(limit).offset(offset)
        )
        total = int((await session.execute(count_stmt)).scalar_one())
        return total, list(result.scalars())


async def get_illustration(illustration_id: str) -> Illustration | None:
    async with engine.new_session() as session:
        session: AsyncSession = session
        return await session.get(Illustration, str(illustration_id))


async def _active_ids(session: AsyncSession, ids: list[str]) -> list[str]:
    if not ids:
        return []
    rows = await session.scalars(
        select(IllustrationImportTask.pixiv_id).where(
            IllustrationImportTask.status.in_(["pending", "running"]),
            IllustrationImportTask.pixiv_id.in_(ids),
        )
    )
    active = {str(value) for value in rows}
    return [item for item in ids if item in active]


async def ensure_available(ids: list[str], *, reject_busy: bool = True) -> list[Illustration]:
    normalized = list(dict.fromkeys(str(item).strip() for item in ids if str(item).strip()))
    async with engine.new_session() as session:
        session: AsyncSession = session
        rows = list(
            (
                await session.scalars(
                    select(Illustration).where(Illustration.id.in_(normalized))
                )
            ).all()
        )
        found = {str(row.id): row for row in rows}
        missing = [item for item in normalized if item not in found]
        if missing:
            raise IllustrationNotFoundError(missing)
        if reject_busy:
            busy = await _active_ids(session, normalized)
            if busy:
                raise IllustrationBusyError(busy)
        return [found[item] for item in normalized]


async def update_illustration(illustration_id: str, values: Mapping[str, Any]) -> Illustration:
    normalized = _validated_edit_values(values)
    async with engine.new_session() as session:
        session: AsyncSession = session
        row = await session.get(Illustration, str(illustration_id))
        if row is None:
            raise IllustrationNotFoundError(str(illustration_id))
        busy = await _active_ids(session, [str(illustration_id)])
        if busy:
            raise IllustrationBusyError(busy)
        for key, value in normalized.items():
            setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return row


async def bulk_update_illustrations(
    ids: list[str], values: Mapping[str, Any]
) -> list[str]:
    normalized_values = _validated_edit_values(values)
    normalized_ids = list(dict.fromkeys(str(item).strip() for item in ids if str(item).strip()))
    if not normalized_ids:
        raise ValueError("至少选择一张图片")
    if len(normalized_ids) > 100:
        raise ValueError("一次最多更新 100 张图片")
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
            raise IllustrationNotFoundError(missing)
        busy = await _active_ids(session, normalized_ids)
        if busy:
            raise IllustrationBusyError(busy)
        for item in normalized_ids:
            row = found[item]
            for key, value in normalized_values.items():
                setattr(row, key, value)
        await session.commit()
    return normalized_ids


@dataclass(slots=True)
class CleanupFailure:
    illustration_id: str
    page: int
    error: str


@dataclass(slots=True)
class DeleteResult:
    removed_ids: list[str]
    deleted_urls: int = 0
    shared_urls: int = 0
    failures: list[CleanupFailure] = field(default_factory=list)


async def delete_illustrations(ids: list[str]) -> DeleteResult:
    normalized_ids = list(dict.fromkeys(str(item).strip() for item in ids if str(item).strip()))
    if not normalized_ids:
        raise ValueError("至少选择一张图片")
    if len(normalized_ids) > 100:
        raise ValueError("一次最多删除 100 张图片")

    target_urls: list[tuple[str, int, str]] = []
    remaining_urls: set[str] = set()
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
            raise IllustrationNotFoundError(missing)
        busy = await _active_ids(session, normalized_ids)
        if busy:
            raise IllustrationBusyError(busy)

        all_rows = list((await session.scalars(select(Illustration))).all())
        target_set = set(normalized_ids)
        for illustration_id in normalized_ids:
            for page, url in _indexed_urls(found[illustration_id].file_urls):
                target_urls.append((illustration_id, page, url))
        for row in all_rows:
            if str(row.id) not in target_set:
                remaining_urls.update(_urls(row.file_urls))

        for row in rows:
            await session.delete(row)
        await session.commit()

    deleted_urls: set[str] = set()
    attempted_urls: set[str] = set()
    shared_urls: set[str] = set()
    failures: list[CleanupFailure] = []
    for illustration_id, page, url in target_urls:
        if url in remaining_urls:
            shared_urls.add(url)
            continue
        if url in attempted_urls:
            continue
        attempted_urls.add(url)
        try:
            await delete_media_url(url)
            deleted_urls.add(url)
        except FileNotFoundError:
            # Deletion is intentionally idempotent: a file that disappeared
            # between the database transaction and cleanup is already in the
            # desired state.
            deleted_urls.add(url)
        except Exception as exc:  # cleanup is best effort after the DB commit
            logger.warning(
                "Failed to clean illustration file %s for %s page %s: %s",
                url,
                illustration_id,
                page,
                exc,
            )
            failures.append(CleanupFailure(illustration_id, page, str(exc)))

    return DeleteResult(
        removed_ids=normalized_ids,
        deleted_urls=len(deleted_urls),
        shared_urls=len(shared_urls),
        failures=failures,
    )
