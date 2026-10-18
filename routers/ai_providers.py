from fastapi import APIRouter, HTTPException

from services.ai import providers
from services.ai.schemas import ProviderInput, PublicProvider

router = APIRouter(prefix="/api/ai/providers", tags=["ai-providers"])


@router.get("", response_model=list[PublicProvider])
async def list_providers():
    return [providers.public(provider) for provider in await providers.all_providers()]


async def save_provider(payload, provider_id=None):
    try:
        return await providers.save(payload, provider_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("", response_model=PublicProvider, status_code=201)
async def create_provider(payload: ProviderInput):
    return await save_provider(payload)


@router.put("/{provider_id}", response_model=PublicProvider)
async def update_provider(provider_id: str, payload: ProviderInput):
    return await save_provider(payload, provider_id)


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str):
    try:
        await providers.remove(provider_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"removed": True}
