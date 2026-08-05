"""Pixiv refresh token management endpoints for the admin console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from registries import config_registry
from services import pixiv

router = APIRouter(prefix="/api/pixiv-tokens", tags=["pixiv-tokens"])


class PixivTokenPayload(BaseModel):
    token: str
    enabled: bool = True


class PixivTokenStatusPayload(BaseModel):
    enabled: bool


class PixivTokenResponse(BaseModel):
    id: int
    token: str
    masked: str
    enabled: bool


class PixivTokenListResponse(BaseModel):
    total: int
    items: list[PixivTokenResponse]


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
async def list_pixiv_tokens() -> PixivTokenListResponse:
    records = await config_registry.get_pixiv_tokens()
    items = [_to_response(record) for record in records if record.id is not None]
    return PixivTokenListResponse(total=len(items), items=items)


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


@router.patch("/enabled", response_model=PixivTokenListResponse)
async def set_all_pixiv_tokens_enabled(
    payload: PixivTokenStatusPayload,
) -> PixivTokenListResponse:
    await config_registry.set_all_pixiv_tokens_enabled(payload.enabled)
    return await list_pixiv_tokens()


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
    return PixivTokenListResponse(total=0, items=[])


@router.post("/reload", response_model=PixivTokenListResponse)
async def reload_pixiv() -> PixivTokenListResponse:
    """Reload Pixiv tokens from the database and refresh enabled ones without restart."""
    try:
        await pixiv.read_token_from_config()
        if pixiv.enabled:
            await pixiv.token_refresh()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to reload Pixiv tokens")
    return await list_pixiv_tokens()


async def _get_token_or_404(token_id: int) -> config_registry.Token:
    for record in await config_registry.get_pixiv_tokens():
        if record.id == token_id:
            return record
    raise HTTPException(status_code=404, detail=f"Pixiv token {token_id} does not exist")
