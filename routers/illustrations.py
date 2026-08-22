"""Illustration import endpoints for the admin console.

Workflow: preview a Pixiv ID (fetch metadata without persisting), let the
user review/adjust fields, then confirm to download + store + persist.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from datetime import datetime

from models import Illustration, IllustrationImportTask
from models.illustrations import build_illust_from_api_dict
from registries import illust_registry
from services import pixiv
from services.illustration_import_runner import (
    create_import_task,
    get_import_task,
    list_import_tasks,
)
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
