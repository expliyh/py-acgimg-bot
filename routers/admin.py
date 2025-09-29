"""REST API routes for administration dashboard."""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from services.admin_store import AdminStore, AutomationRule, FeatureConfig, Group, PrivateChat


router = APIRouter(prefix="/api", tags=["admin"])


class GroupIn(BaseModel):
    name: str = Field(..., description="Group name", min_length=1)
    description: str = Field("", description="Group description")
    is_active: Optional[bool] = Field(default=True)
    tags: List[str] = Field(default_factory=list)


class GroupOut(BaseModel):
    id: str
    name: str
    description: str
    is_active: bool
    tags: List[str]

    class Config:
        orm_mode = True


class PrivateChatIn(BaseModel):
    username: str = Field(..., min_length=1)
    alias: Optional[str] = None
    is_muted: Optional[bool] = False
    last_message_preview: Optional[str] = None


class PrivateChatOut(BaseModel):
    id: str
    username: str
    alias: Optional[str]
    is_muted: bool
    last_message_preview: Optional[str]

    class Config:
        orm_mode = True


class FeatureConfigIn(BaseModel):
    name: str
    enabled: Optional[bool] = True
    description: Optional[str] = None
    options: Dict[str, str] = Field(default_factory=dict)


class FeatureConfigOut(BaseModel):
    id: str
    name: str
    enabled: bool
    description: str
    options: Dict[str, str]

    class Config:
        orm_mode = True


class AutomationRuleIn(BaseModel):
    name: str
    trigger: str
    action: str
    enabled: Optional[bool] = True


class AutomationRuleOut(BaseModel):
    id: str
    name: str
    trigger: str
    action: str
    enabled: bool

    class Config:
        orm_mode = True


class DashboardStats(BaseModel):
    groups: int
    active_groups: int
    private_chats: int
    muted_chats: int
    automations: int


def get_store(request: Request) -> AdminStore:
    store = getattr(request.app.state, "admin_store", None)
    if store is None:
        raise RuntimeError("Admin store has not been configured")
    return store


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard_snapshot(store: AdminStore = Depends(get_store)) -> DashboardStats:
    data = await store.dashboard_snapshot()
    return DashboardStats(**data)


@router.get("/groups", response_model=List[GroupOut])
async def list_groups(store: AdminStore = Depends(get_store)) -> List[Group]:
    return await store.list_groups()


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(payload: GroupIn, store: AdminStore = Depends(get_store)) -> Group:
    group = await store.create_group(payload.name, payload.description, payload.tags)
    if payload.is_active is not None:
        group = await store.update_group(group.id, is_active=payload.is_active)
    return group


@router.put("/groups/{group_id}", response_model=GroupOut)
async def update_group(group_id: str, payload: GroupIn, store: AdminStore = Depends(get_store)) -> Group:
    try:
        return await store.update_group(
            group_id,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            tags=payload.tags,
        )
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: str, store: AdminStore = Depends(get_store)) -> None:
    try:
        await store.delete_group(group_id)
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/private-chats", response_model=List[PrivateChatOut])
async def list_private_chats(store: AdminStore = Depends(get_store)) -> List[PrivateChat]:
    return await store.list_private_chats()


@router.post("/private-chats", response_model=PrivateChatOut, status_code=status.HTTP_201_CREATED)
async def create_private_chat(payload: PrivateChatIn, store: AdminStore = Depends(get_store)) -> PrivateChat:
    chat = await store.create_private_chat(payload.username, payload.alias)
    return await store.update_private_chat(
        chat.id,
        alias=payload.alias,
        is_muted=payload.is_muted,
        last_message_preview=payload.last_message_preview,
    )


@router.put("/private-chats/{chat_id}", response_model=PrivateChatOut)
async def update_private_chat(chat_id: str, payload: PrivateChatIn, store: AdminStore = Depends(get_store)) -> PrivateChat:
    try:
        return await store.update_private_chat(
            chat_id,
            username=payload.username,
            alias=payload.alias,
            is_muted=payload.is_muted,
            last_message_preview=payload.last_message_preview,
        )
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/private-chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_private_chat(chat_id: str, store: AdminStore = Depends(get_store)) -> None:
    try:
        await store.delete_private_chat(chat_id)
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/features", response_model=List[FeatureConfigOut])
async def list_feature_configs(store: AdminStore = Depends(get_store)) -> List[FeatureConfig]:
    return await store.list_feature_configs()


@router.post("/features", response_model=FeatureConfigOut, status_code=status.HTTP_201_CREATED)
async def upsert_feature_config(payload: FeatureConfigIn, store: AdminStore = Depends(get_store)) -> FeatureConfig:
    return await store.upsert_feature_config(
        payload.name,
        enabled=payload.enabled,
        description=payload.description,
        options=payload.options,
    )


@router.delete("/features/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feature_config(config_id: str, store: AdminStore = Depends(get_store)) -> None:
    try:
        await store.delete_feature_config(config_id)
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/automations", response_model=List[AutomationRuleOut])
async def list_automation_rules(store: AdminStore = Depends(get_store)) -> List[AutomationRule]:
    return await store.list_automation_rules()


@router.post("/automations", response_model=AutomationRuleOut, status_code=status.HTTP_201_CREATED)
async def create_automation_rule(payload: AutomationRuleIn, store: AdminStore = Depends(get_store)) -> AutomationRule:
    return await store.create_automation_rule(
        payload.name,
        payload.trigger,
        payload.action,
        enabled=payload.enabled if payload.enabled is not None else True,
    )


@router.put("/automations/{rule_id}", response_model=AutomationRuleOut)
async def update_automation_rule(rule_id: str, payload: AutomationRuleIn, store: AdminStore = Depends(get_store)) -> AutomationRule:
    try:
        return await store.update_automation_rule(
            rule_id,
            name=payload.name,
            trigger=payload.trigger,
            action=payload.action,
            enabled=payload.enabled,
        )
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/automations/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation_rule(rule_id: str, store: AdminStore = Depends(get_store)) -> None:
    try:
        await store.delete_automation_rule(rule_id)
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
