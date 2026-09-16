"""Illustration import endpoints for the admin console.

Workflow: preview a Pixiv ID (fetch metadata without persisting), let the
user review/adjust fields, then confirm to download + store + persist.
"""

from __future__ import annotations

import os
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from datetime import datetime

from models import Illustration, IllustrationImportTask
from models.illustrations import build_illust_from_api_dict
from registries import illust_registry
from services import pixiv
from services.illustration_import_runner import (
    create_import_task,
    create_refresh_tasks,
    get_import_task,
    list_import_tasks,
)
from services.illustration_fields import normalize_tags
from services.illustration_gallery import (
    DeleteResult,
    IllustrationBusyError,
    IllustrationNotFoundError,
    bulk_update_illustrations,
    delete_illustrations,
    get_illustration,
    list_illustrations,
    update_illustration,
)
from services.illustration_media import MediaAccessError, read_media_url
from services.manual_illustration_importer import (
    MAX_IMAGE_BYTES,
    import_manual_illustration,
)
from utils.api_contract import page_meta, page_offset

router = APIRouter(prefix="/api/illustrations", tags=["illustrations"])


class ManualIllustrationResponse(BaseModel):
    id: str
    title: str
    storage_url: str


@router.post("/manual", response_model=ManualIllustrationResponse)
async def create_manual_illustration(
    image: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=64),
    author_name: str | None = Form(None, max_length=64),
    source_url: str | None = Form(None),
    author_url: str | None = Form(None),
    caption: str | None = Form(None),
    tags: str | None = Form(None),
    is_ai: bool = Form(False),
    is_r18: bool = Form(False),
    is_r18g: bool = Form(False),
) -> ManualIllustrationResponse:
    """Store a non-Pixiv image submitted from the administrator console."""
    try:
        result = await import_manual_illustration(
            await image.read(MAX_IMAGE_BYTES + 1),
            filename=image.filename or "image.jpg",
            title=title,
            author_name=author_name,
            source_url=source_url,
            author_url=author_url,
            caption=caption,
            tags=[item.strip() for item in (tags or "").replace("，", ",").split(",") if item.strip()],
            is_ai=is_ai,
            is_r18=is_r18,
            is_r18g=is_r18g,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ManualIllustrationResponse(
        id=result.illustration.id,
        title=result.illustration.title or result.illustration.id,
        storage_url=result.storage_url,
    )

_PIXIV_CDN_HOST = "i.pximg.net"
_PIXIV_CDN_ORIGIN = f"https://{_PIXIV_CDN_HOST}"


async def _fetch_pixiv_bytes(relative_url: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"Referer": "https://app-api.pixiv.net/"}
    # Keep the network destination independent from request data.  Using a fixed
    # base URL also makes the SSRF boundary explicit for static analysis.
    async with aiohttp.ClientSession(
        base_url=_PIXIV_CDN_ORIGIN, timeout=timeout
    ) as session:
        async with session.get(
            relative_url, headers=headers, allow_redirects=False
        ) as response:
            if response.status != 200:
                raise HTTPException(
                    status_code=502, detail=f"获取图片失败：HTTP {response.status}"
                )
            return await response.read()


class PixivIdPayload(BaseModel):
    pixiv_id: int = Field(..., gt=0)


class IllustrationImportPayload(PixivIdPayload):
    title: str | None = None
    caption: str | None = None
    tags: list[str] | None = None
    sanity_level: int | None = Field(default=None, ge=0, le=10)
    r18g: bool | None = None
    is_ai: bool | None = None


class IllustrationPreviewResponse(BaseModel):
    id: str
    title: str | None
    author_id: str
    author_name: str | None
    page_count: int
    sanity_level: int
    r18g: bool
    x_restrict: int
    tags: list[str]
    caption: str | None
    is_ai: bool
    exists: bool
    preview_urls: list[str]


class IllustrationImportTaskResponse(BaseModel):
    id: int
    pixiv_id: str
    title: str | None
    status: str
    created: bool | None
    total_pages: int | None
    current_page: int | None
    error_message: str | None
    result: dict | None
    created_at: datetime
    finished_at: datetime | None


class IllustrationImportTaskListResponse(BaseModel):
    total: int
    items: list[IllustrationImportTaskResponse]
    page: int
    page_size: int
    pages: int


def _task_to_response(task: IllustrationImportTask) -> IllustrationImportTaskResponse:
    return IllustrationImportTaskResponse(
        id=task.id,
        pixiv_id=task.pixiv_id,
        title=task.title,
        status=task.status,
        created=task.created,
        total_pages=task.total_pages,
        current_page=task.current_page,
        error_message=task.error_message,
        result=task.result,
        created_at=task.created_at,
        finished_at=task.finished_at,
    )


@router.post("/import", response_model=IllustrationImportTaskResponse)
async def create_import_task_endpoint(
    payload: IllustrationImportPayload,
) -> IllustrationImportTaskResponse:
    """Create a background import task; progress is tracked in the task history."""
    if not pixiv.enabled:
        raise HTTPException(status_code=400, detail="Pixiv 功能未启用，请先配置有效的 Pixiv Token")

    overrides = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if key != "pixiv_id"
    }
    task = await create_import_task(payload.pixiv_id, overrides)
    return _task_to_response(task)


@router.get("/tasks", response_model=IllustrationImportTaskListResponse)
async def list_import_tasks_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, pattern="^(pending|running|success|failed)$"),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> IllustrationImportTaskListResponse:
    """List recent import tasks, newest first."""
    allowed_sort_fields = {"id", "pixiv_id", "title", "status", "created_at", "finished_at"}
    if sort_by not in allowed_sort_fields:
        raise HTTPException(status_code=422, detail=f"不支持的排序字段: {sort_by}")
    total, tasks = await list_import_tasks(
        limit=page_size,
        offset=page_offset(page, page_size),
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    meta = page_meta(total, page, page_size)
    return IllustrationImportTaskListResponse(
        items=[_task_to_response(task) for task in tasks],
        **meta.model_dump(),
    )


@router.get("/tasks/{task_id}", response_model=IllustrationImportTaskResponse)
async def get_import_task_endpoint(task_id: int) -> IllustrationImportTaskResponse:
    """Get a single import task (used to poll import progress)."""
    task = await get_import_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"导入任务 {task_id} 不存在")
    return _task_to_response(task)


def _preview_from_illust(
    illust: Illustration, *, exists: bool, preview_urls: list[str]
) -> IllustrationPreviewResponse:
    return IllustrationPreviewResponse(
        id=illust.id,
        title=illust.title,
        author_id=illust.author_id,
        author_name=illust.author_name,
        page_count=illust.page_count,
        sanity_level=illust.sanity_level,
        r18g=illust.r18g,
        x_restrict=illust.x_restrict,
        tags=list(illust.tags or []),
        caption=illust.caption,
        is_ai=illust.is_ai,
        exists=exists,
        preview_urls=preview_urls,
    )


def _first_available_url(image_urls: dict) -> str:
    for key in ("square_medium", "medium", "large"):
        value = image_urls.get(key)
        if value:
            return value
    return ""


def _extract_preview_urls(illust_data: dict, page_count: int) -> list[str]:
    urls: list[str] = []
    if page_count == 1:
        image_urls = illust_data.get("image_urls") or {}
        first = _first_available_url(image_urls)
        if first:
            urls.append(first)
    else:
        for page in illust_data.get("meta_pages") or []:
            image_urls = (page or {}).get("image_urls") or {}
            first = _first_available_url(image_urls)
            if first:
                urls.append(first)
    return urls


def _guess_media_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")


@router.post("/preview", response_model=IllustrationPreviewResponse)
async def preview_illustration(payload: PixivIdPayload) -> IllustrationPreviewResponse:
    """Fetch illustration metadata from Pixiv without persisting anything."""
    if not pixiv.enabled:
        raise HTTPException(status_code=400, detail="Pixiv 功能未启用，请先配置有效的 Pixiv Token")

    try:
        response = await pixiv.get_raw(payload.pixiv_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"从 Pixiv 获取插画失败：{exc}")

    illust_data = response.get("illust")
    if not isinstance(illust_data, dict):
        raise HTTPException(status_code=502, detail="Pixiv 响应缺少 illust 数据")

    try:
        illust = build_illust_from_api_dict(illust_data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"解析 Pixiv 插画数据失败：{exc}")

    existing = await illust_registry.get_illust_info(payload.pixiv_id)
    preview_urls = _extract_preview_urls(illust_data, illust.page_count)
    return _preview_from_illust(illust, exists=existing is not None, preview_urls=preview_urls)


@router.get("/image")
async def proxy_image(url: str) -> Response:
    """Proxy a Pixiv CDN image (requires a referer header) for inline preview."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise HTTPException(status_code=400, detail="仅允许代理 Pixiv CDN 图片")

    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != _PIXIV_CDN_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
    ):
        raise HTTPException(status_code=400, detail="仅允许代理 Pixiv CDN 图片")

    # Pass only the path and query to the HTTP client.  The scheme and authority
    # are supplied by the trusted constant in _fetch_pixiv_bytes.
    relative_url = urlunsplit(("", "", parsed.path, parsed.query, ""))

    try:
        content = await _fetch_pixiv_bytes(relative_url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"获取图片失败：{exc}")

    return Response(content=content, media_type=_guess_media_type(parsed.path))


# ---------------------------------------------------------------------------
# Gallery / catalogue management API
# ---------------------------------------------------------------------------


class IllustrationPageResponse(BaseModel):
    index: int
    media_url: str
    has_storage_url: bool


class IllustrationListItem(BaseModel):
    id: str
    title: str | None
    source_type: str
    author_id: str
    author_name: str | None
    page_count: int
    sanity_level: int
    r18g: bool
    x_restrict: int
    is_ai: bool
    tags: list[str]
    thumbnail_url: str | None
    has_media: bool


class IllustrationDetail(IllustrationListItem):
    caption: str | None
    source_url: str | None
    author_url: str | None
    pages: list[IllustrationPageResponse]


class IllustrationListResponse(BaseModel):
    total: int
    items: list[IllustrationListItem]
    page: int
    page_size: int
    pages: int


class IllustrationUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=64)
    author_name: str | None = Field(default=None, max_length=64)
    author_url: str | None = Field(default=None, max_length=2048)
    source_url: str | None = Field(default=None, max_length=2048)
    caption: str | None = Field(default=None, max_length=20000)
    tags: list[str] | None = Field(default=None, max_length=100)
    sanity_level: StrictInt = Field(default=5, ge=0, le=10)
    x_restrict: StrictInt = Field(default=0, ge=0, le=2)
    r18g: StrictBool = False
    is_ai: StrictBool = False

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if len(text) > 64:
                raise ValueError("单个标签不能超过 64 个字符")
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @model_validator(mode="after")
    def require_a_field(self) -> "IllustrationUpdatePayload":
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要修改的字段")
        return self


class IllustrationIdsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("ids")
    @classmethod
    def normalize_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw).strip()
            if not item or len(item) > 20 or "/" in item or "\\" in item:
                raise ValueError("插画 ID 无效")
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        if not normalized:
            raise ValueError("至少选择一张图片")
        return normalized


class IllustrationBulkUpdatePayload(IllustrationIdsPayload):
    patch: IllustrationUpdatePayload


class IllustrationCleanupFailureResponse(BaseModel):
    illustration_id: str
    page: int
    error: str


class IllustrationDeleteResponse(BaseModel):
    removed: bool
    removed_ids: list[str]
    deleted_urls: int
    shared_urls: int
    cleanup_failures: list[IllustrationCleanupFailureResponse]


class IllustrationBulkUpdateResponse(BaseModel):
    updated_ids: list[str]


class IllustrationRefreshBatchResponse(BaseModel):
    tasks: list[IllustrationImportTaskResponse]


def _illustration_media_url(illustration_id: str, page: int) -> str:
    return f"/api/illustrations/{quote(str(illustration_id), safe='')}/pages/{page}/media"


def _storage_pages(illust: Illustration) -> list[str | None]:
    raw = illust.file_urls
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        values = [raw]
    else:
        values = []
    count = max(int(illust.page_count or 0), 0)
    return [
        value.strip() if isinstance(value, str) and value.strip() else None
        for value in (values[:count] + [None] * max(0, count - len(values)))
    ]


def _illustration_list_item(illust: Illustration) -> IllustrationListItem:
    pages = _storage_pages(illust)
    # The first stored page is the canonical cover.  Do not silently promote a
    # later page when page zero is missing; the UI should show the missing-media
    # placeholder and make the data problem visible.
    has_cover = bool(pages and pages[0])
    return IllustrationListItem(
        id=str(illust.id),
        title=illust.title,
        source_type=str(getattr(illust, "source_type", "pixiv") or "pixiv"),
        author_id=str(illust.author_id),
        author_name=illust.author_name,
        page_count=max(int(illust.page_count or 0), 0),
        sanity_level=int(illust.sanity_level),
        r18g=bool(illust.r18g),
        x_restrict=int(illust.x_restrict),
        is_ai=bool(illust.is_ai),
        tags=normalize_tags(illust.tags),
        thumbnail_url=(
            _illustration_media_url(str(illust.id), 0)
            if has_cover
            else None
        ),
        has_media=any(pages),
    )


def _illustration_detail(illust: Illustration) -> IllustrationDetail:
    base = _illustration_list_item(illust)
    pages = _storage_pages(illust)
    return IllustrationDetail(
        **base.model_dump(),
        caption=illust.caption,
        source_url=getattr(illust, "source_url", None),
        author_url=getattr(illust, "author_url", None),
        pages=[
            IllustrationPageResponse(
                index=index,
                media_url=_illustration_media_url(str(illust.id), index),
                has_storage_url=bool(value),
            )
            for index, value in enumerate(pages)
        ],
    )


def _delete_response(result: DeleteResult) -> IllustrationDeleteResponse:
    return IllustrationDeleteResponse(
        removed=True,
        removed_ids=result.removed_ids,
        deleted_urls=result.deleted_urls,
        shared_urls=result.shared_urls,
        cleanup_failures=[
            IllustrationCleanupFailureResponse(
                illustration_id=failure.illustration_id,
                page=failure.page,
                error=failure.error,
            )
            for failure in result.failures
        ],
    )


@router.get("", response_model=IllustrationListResponse)
async def list_illustrations_endpoint(
    q: str | None = Query(default=None),
    source_type: Literal["pixiv", "manual"] | None = Query(default=None),
    r18g: bool | None = Query(default=None),
    is_ai: bool | None = Query(default=None),
    x_restrict: int | None = Query(default=None, ge=0, le=2),
    sanity_min: int | None = Query(default=None, ge=0, le=10),
    sanity_max: int | None = Query(default=None, ge=0, le=10),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    sort_by: str = Query(default="id"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> IllustrationListResponse:
    if sanity_min is not None and sanity_max is not None and sanity_min > sanity_max:
        raise HTTPException(status_code=422, detail="分级范围无效：最小值不能大于最大值")
    try:
        total, rows = await list_illustrations(
            limit=page_size,
            offset=page_offset(page, page_size),
            q=q.strip() if q else None,
            source_type=source_type,
            r18g=r18g,
            is_ai=is_ai,
            x_restrict=x_restrict,
            sanity_min=sanity_min,
            sanity_max=sanity_max,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    meta = page_meta(total, page, page_size)
    return IllustrationListResponse(
        items=[_illustration_list_item(row) for row in rows],
        **meta.model_dump(),
    )


@router.post("/bulk/update", response_model=IllustrationBulkUpdateResponse)
async def bulk_update_illustrations_endpoint(
    payload: IllustrationBulkUpdatePayload,
) -> IllustrationBulkUpdateResponse:
    try:
        updated_ids = await bulk_update_illustrations(
            payload.ids,
            payload.patch.model_dump(exclude_unset=True),
        )
    except IllustrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IllustrationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return IllustrationBulkUpdateResponse(updated_ids=updated_ids)


@router.post("/bulk/delete", response_model=IllustrationDeleteResponse)
async def bulk_delete_illustrations_endpoint(
    payload: IllustrationIdsPayload,
) -> IllustrationDeleteResponse:
    try:
        result = await delete_illustrations(payload.ids)
    except IllustrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IllustrationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _delete_response(result)


@router.post("/bulk/refresh", response_model=IllustrationRefreshBatchResponse)
async def bulk_refresh_illustrations_endpoint(
    payload: IllustrationIdsPayload,
) -> IllustrationRefreshBatchResponse:
    if not pixiv.enabled:
        raise HTTPException(status_code=400, detail="Pixiv 功能未启用，请先配置有效的 Pixiv Token")
    try:
        tasks = await create_refresh_tasks(payload.ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return IllustrationRefreshBatchResponse(tasks=[_task_to_response(task) for task in tasks])


@router.post("/{illustration_id}/refresh", response_model=IllustrationImportTaskResponse)
async def refresh_illustration_endpoint(
    illustration_id: str,
) -> IllustrationImportTaskResponse:
    if not pixiv.enabled:
        raise HTTPException(status_code=400, detail="Pixiv 功能未启用，请先配置有效的 Pixiv Token")
    try:
        tasks = await create_refresh_tasks([illustration_id])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _task_to_response(tasks[0])


@router.get("/{illustration_id}/pages/{page}/media")
async def illustration_media_endpoint(illustration_id: str, page: int) -> Response:
    illust = await get_illustration(illustration_id)
    if illust is None:
        raise HTTPException(status_code=404, detail=f"插画 {illustration_id} 不存在")
    if page < 0 or page >= int(illust.page_count or 0):
        raise HTTPException(status_code=404, detail="请求的页码不存在")
    urls = _storage_pages(illust)
    stored_url = urls[page] if page < len(urls) else None
    if not stored_url:
        raise HTTPException(status_code=404, detail="该页面没有可用的存储图片")
    try:
        media = await read_media_url(stored_url)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="存储图片不存在") from exc
    except (MediaAccessError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"读取存储图片失败：{exc}") from exc
    return Response(
        content=media.data,
        media_type=media.media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{illustration_id}", response_model=IllustrationDetail)
async def get_illustration_endpoint(illustration_id: str) -> IllustrationDetail:
    illust = await get_illustration(illustration_id)
    if illust is None:
        raise HTTPException(status_code=404, detail=f"插画 {illustration_id} 不存在")
    return _illustration_detail(illust)


@router.patch("/{illustration_id}", response_model=IllustrationDetail)
async def update_illustration_endpoint(
    illustration_id: str,
    payload: IllustrationUpdatePayload,
) -> IllustrationDetail:
    try:
        updated = await update_illustration(
            illustration_id,
            payload.model_dump(exclude_unset=True),
        )
    except IllustrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IllustrationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _illustration_detail(updated)


@router.delete("/{illustration_id}", response_model=IllustrationDeleteResponse)
async def delete_illustration_endpoint(illustration_id: str) -> IllustrationDeleteResponse:
    try:
        result = await delete_illustrations([illustration_id])
    except IllustrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IllustrationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _delete_response(result)
