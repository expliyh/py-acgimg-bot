"""Bot token management endpoints for the admin console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import bot
from registries import config_registry

router = APIRouter(prefix="/api/bot-tokens", tags=["bot-tokens"])


class BotTokenPayload(BaseModel):
    token: str
    enabled: bool = True


class BotTokenStatusPayload(BaseModel):
    enabled: bool


class BotTokenResponse(BaseModel):
    configured: bool
    token: str | None
    masked: str | None
    enabled: bool | None


def _mask(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _to_response(current: config_registry.Token | None) -> BotTokenResponse:
    if current is None:
        return BotTokenResponse(
            configured=False,
            token=None,
            masked=None,
            enabled=None,
        )
    return BotTokenResponse(
        configured=True,
        token=current.token,
        masked=_mask(current.token),
        enabled=current.enable,
    )


@router.get("", response_model=BotTokenResponse)
async def get_bot_token() -> BotTokenResponse:
    current = await config_registry.get_bot_token()
    return _to_response(current)


@router.put("", response_model=BotTokenResponse)
async def set_bot_token(payload: BotTokenPayload) -> BotTokenResponse:
    try:
        current = await config_registry.set_bot_token(
            payload.token, enabled=payload.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_response(current)


@router.patch("/status", response_model=BotTokenResponse)
async def set_bot_token_enabled(payload: BotTokenStatusPayload) -> BotTokenResponse:
    try:
        await config_registry.set_bot_token_enabled(payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    current = await config_registry.get_bot_token()
    return _to_response(current)


@router.delete("", response_model=BotTokenResponse)
async def delete_bot_token() -> BotTokenResponse:
    await config_registry.delete_bot_token()
    return _to_response(None)


@router.post("/reload", response_model=BotTokenResponse)
async def reload_bot() -> BotTokenResponse:
    """Re-initialize the Telegram bot so token changes take effect without a restart."""
    try:
        await bot.tg_bot.config()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to reload Telegram bot")
    current = await config_registry.get_bot_token()
    return _to_response(current)
