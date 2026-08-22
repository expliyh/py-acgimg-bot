"""Pixiv refresh token management endpoints for the admin console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from registries import config_registry
from services import pixiv

router = APIRouter(prefix="/api/pixiv-tokens", tags=["pixiv-tokens"])


class PixivTokenPayload(BaseModel):
    token: str
    enabled: bool = True


class PixivTokenStatusPayload(BaseModel):
    enabled: bool


class PixivTokenBatchStatusPayload(PixivTokenStatusPayload):
    ids: list[int] | None = None


class PixivTokenResponse(BaseModel):
    id: int
    token: str
    masked: str
    enabled: bool


class PixivTokenListResponse(BaseModel):
    total: int
    items: list[PixivTokenResponse]
    page: int
    page_size: int
    pages: int


def _mask(token: str | None) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _to_response(record: config_registry.Token) -> PixivTokenResponse:
    return PixivTokenResponse(
        id=record.id or 0,
        token=record.token,
        masked=_mask(record.token),
        enabled=record.enable,
    )


@router.get("", response_model=PixivTokenListResponse)
async def list_pixiv_tokens(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    sort_by: str = Query(default="id"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> PixivTokenListResponse:
    records = await config_registry.get_pixiv_tokens()
    items = [_to_response(record) for record in records if record.id is not None]
    if sort_by not in {"id", "enabled"}:
        raise HTTPException(status_code=422, detail=f"不支持的排序字段: {sort_by}")
    items.sort(key=lambda item: getattr(item, sort_by), reverse=sort_order == "desc")
    total = len(items)
    offset = (page - 1) * page_size
    pages = (total + page_size - 1) // page_size if total else 0
    return PixivTokenListResponse(
        total=total,
        items=items[offset : offset + page_size],
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post("", response_model=PixivTokenResponse)
async def add_pixiv_token(payload: PixivTokenPayload) -> PixivTokenResponse:
    try:
        record = await config_registry.add_pixiv_token(
            payload.token, enabled=payload.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_response(record)


@router.put("/{token_id}", response_model=PixivTokenResponse)
async def update_pixiv_token(
    token_id: int, payload: PixivTokenPayload
) -> PixivTokenResponse:
    if not payload.token.strip():
        raise HTTPException(status_code=400, detail="Pixiv token cannot be empty")
    try:
        await config_registry.update_pixiv_token(token_id, payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    record = await _get_token_or_404(token_id)
    return _to_response(record)


@router.patch("", response_model=PixivTokenListResponse)
async def set_all_pixiv_tokens_enabled(
    payload: PixivTokenBatchStatusPayload,
) -> PixivTokenListResponse:
    if payload.ids is None:
        await config_registry.set_all_pixiv_tokens_enabled(payload.enabled)
    else:
        try:
            await config_registry.set_pixiv_tokens_enabled(payload.ids, payload.enabled)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await list_pixiv_tokens(page=1, page_size=25, sort_by="id", sort_order="asc")


@router.patch("/{token_id}/status", response_model=PixivTokenResponse)
async def set_pixiv_token_enabled(
    token_id: int, payload: PixivTokenStatusPayload
) -> PixivTokenResponse:
    try:
        await config_registry.set_pixiv_token_enabled(token_id, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    record = await _get_token_or_404(token_id)
    return _to_response(record)


@router.delete("/{token_id}", response_model=PixivTokenResponse)
async def delete_pixiv_token(token_id: int) -> PixivTokenResponse:
    record = await _get_token_or_404(token_id)
    await config_registry.delete_pixiv_token(token_id)
    return _to_response(record)


@router.delete("", response_model=PixivTokenListResponse)
async def delete_all_pixiv_tokens() -> PixivTokenListResponse:
    await config_registry.delete_all_pixiv_tokens()
    return PixivTokenListResponse(total=0, items=[], page=1, page_size=25, pages=0)


@router.post("/reload", response_model=PixivTokenListResponse)
async def reload_pixiv() -> PixivTokenListResponse:
    """Reload Pixiv tokens from the database and refresh enabled ones without restart."""
    try:
        await pixiv.read_token_from_config()
        if pixiv.enabled:
            await pixiv.token_refresh()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to reload Pixiv tokens")
    return await list_pixiv_tokens(page=1, page_size=25, sort_by="id", sort_order="asc")


async def _get_token_or_404(token_id: int) -> config_registry.Token:
    for record in await config_registry.get_pixiv_tokens():
        if record.id == token_id:
            return record
    raise HTTPException(status_code=404, detail=f"Pixiv token {token_id} does not exist")
