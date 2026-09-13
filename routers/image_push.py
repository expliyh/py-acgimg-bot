"""Administrative API for scheduled and immediate image pushes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import desc, func, select

from models import Group, ImagePushBatch, ImagePushDelivery, ImagePushPlan
from registries.engine import engine
from services import image_push
from utils.api_contract import page_meta, page_offset

router = APIRouter(prefix="/api/image-push", tags=["image-push"])


class PushConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_scope: Literal["selected", "all"] = "selected"
    group_ids: list[int] = Field(default_factory=list)
    mode: Literal["fixed_same", "fixed_different", "random_same", "random_different"]
    pid: str | None = None
    pid_by_group: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_targets_and_mode(self):
        self.group_ids = list(dict.fromkeys(self.group_ids))
        if self.target_scope == "selected" and not self.group_ids:
            raise ValueError("选择群组时至少需要一个群")
        if self.target_scope == "all" and self.group_ids:
            raise ValueError("选择所有群时不应提供 group_ids")
        if self.mode == "fixed_same":
            if not self.pid or self.pid_by_group is not None:
                raise ValueError("固定相同模式需要一个 PID，不接受逐群 PID 映射")
            self.pid = image_push.normalize_pid_spec(self.pid)
        elif self.mode == "fixed_different":
            if self.pid is not None or not self.pid_by_group:
                raise ValueError("固定不同模式需要逐群 PID 映射")
            self.pid_by_group = {
                str(group_id): image_push.normalize_pid_spec(spec)
                for group_id, spec in self.pid_by_group.items()
            }
        elif self.pid is not None or self.pid_by_group is not None:
            raise ValueError("随机模式不接受 PID")
        return self


class PlanPayload(PushConfig):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    repeat: Literal["once", "daily", "weekly", "interval"] = "once"
    due_at: datetime
    interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def validate_schedule(self):
        if not self.name.strip():
            raise ValueError("计划名称不能为空")
        if self.due_at.tzinfo is None:
            raise ValueError("due_at 必须包含时区")
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError) as exc:
            raise ValueError("无效时区") from exc
        if self.repeat == "interval" and self.interval_seconds is None:
            raise ValueError("固定间隔计划必须提供 interval_seconds")
        if self.repeat != "interval" and self.interval_seconds is not None:
            raise ValueError("只有固定间隔计划可以提供 interval_seconds")
        return self


class PlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    repeat: Literal["once", "daily", "weekly", "interval"] | None = None
    due_at: datetime | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    timezone: str | None = None
    target_scope: Literal["selected", "all"] | None = None
    group_ids: list[int] | None = None
    mode: Literal["fixed_same", "fixed_different", "random_same", "random_different"] | None = None
    pid: str | None = None
    pid_by_group: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_name(self):
        if self.name is not None and not self.name.strip():
            raise ValueError("计划名称不能为空")
        for field in (
            "name",
            "enabled",
            "repeat",
            "timezone",
            "target_scope",
            "group_ids",
            "mode",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} 不能为 null")
        return self


class ManualPayload(PushConfig):
    pass


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    enabled: bool
    repeat: str
    due_at: datetime
    next_run_at: datetime
    interval_seconds: int | None
    timezone: str
    target_scope: str
    group_ids: list[int]
    mode: str
    pid: str | None
    pid_by_group: dict[str, str] | None
    created_at: datetime
    updated_at: datetime
    latest_batch_id: str | None = None
    latest_batch_state: str | None = None


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str
    group_id: int
    state: str
    pixiv_id: str | None
    page: int | None
    telegram_message_id: int | None
    reason: str | None
    attempts: int
    next_attempt_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str | None
    trigger: str
    state: str
    due_at: datetime
    config_snapshot: dict
    summary: dict
    result: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    deliveries: list[DeliveryResponse] | None = None


class PageResponse(BaseModel):
    total: int
    items: list
    page: int
    page_size: int
    pages: int


async def _validate_groups(value: PushConfig, *, require_all_mapping: bool = True) -> None:
    if value.target_scope == "selected":
        existing = await image_push.existing_group_ids(value.group_ids)
        missing = [group_id for group_id in value.group_ids if group_id not in existing]
        if missing:
            raise HTTPException(422, f"群组不存在：{', '.join(map(str, missing))}")
    if value.mode == "fixed_different" and value.target_scope == "selected":
        missing = [
            str(group_id)
            for group_id in value.group_ids
            if str(group_id) not in (value.pid_by_group or {})
        ]
        if missing:
            raise HTTPException(422, f"缺少群组 PID 映射：{', '.join(missing)}")
    if require_all_mapping and value.mode == "fixed_different" and value.target_scope == "all":
        async with engine.new_session() as session:
            ids = list((await session.scalars(select(Group.id))).all())
        missing = [str(group_id) for group_id in ids if str(group_id) not in (value.pid_by_group or {})]
        if missing:
            raise HTTPException(422, f"当前群组缺少 PID 映射：{', '.join(missing)}")


async def _latest_batch(plan_id: str) -> ImagePushBatch | None:
    async with engine.new_session() as session:
        return await session.scalar(
            select(ImagePushBatch)
            .where(ImagePushBatch.plan_id == plan_id)
            .order_by(desc(ImagePushBatch.created_at), desc(ImagePushBatch.id))
            .limit(1)
        )


def _plan_response(plan: ImagePushPlan, latest: ImagePushBatch | None) -> PlanResponse:
    return PlanResponse(
        id=plan.id,
        name=plan.name,
        enabled=plan.enabled,
        repeat=plan.repeat,
        due_at=plan.due_at,
        next_run_at=plan.next_run_at,
        interval_seconds=plan.interval_seconds,
        timezone=plan.timezone,
        target_scope=plan.target_scope,
        group_ids=list(plan.group_ids or []),
        mode=plan.mode,
        pid=plan.pid,
        pid_by_group=plan.pid_by_group,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        latest_batch_id=latest.id if latest else None,
        latest_batch_state=latest.state if latest else None,
    )


def _batch_response(batch: ImagePushBatch, rows: list[ImagePushDelivery] | None = None) -> BatchResponse:
    return BatchResponse(
        id=batch.id,
        plan_id=batch.plan_id,
        trigger=batch.trigger,
        state=batch.state,
        due_at=batch.due_at,
        config_snapshot=batch.config_snapshot or {},
        summary=batch.summary or {},
        result=batch.result,
        created_at=batch.created_at,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        deliveries=[DeliveryResponse.model_validate(row) for row in rows] if rows is not None else None,
    )


@router.get("/plans", response_model=PageResponse)
async def get_plans(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    total, plans = await image_push.list_plans(limit=page_size, offset=page_offset(page, page_size))
    items = [_plan_response(plan, await _latest_batch(plan.id)) for plan in plans]
    return PageResponse(items=items, **page_meta(total, page, page_size).model_dump())


@router.post("/plans", response_model=PlanResponse)
async def post_plan(payload: PlanPayload):
    await _validate_groups(payload)
    try:
        plan = await image_push.create_plan(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _plan_response(plan, None)


@router.patch("/plans/{plan_id}", response_model=PlanResponse)
async def patch_plan(plan_id: str, payload: PlanPatch):
    current = await image_push.get_plan(plan_id)
    if current is None:
        raise HTTPException(404, "推送计划不存在")
    values = payload.model_dump(exclude_unset=True)
    requested_mode = values.get("mode", current.mode)
    merged = {
        "target_scope": values.get("target_scope", current.target_scope),
        "group_ids": values.get("group_ids", current.group_ids or []),
        "mode": requested_mode,
        "pid": values.get("pid", current.pid) if requested_mode == "fixed_same" else None,
        "pid_by_group": (
            values.get("pid_by_group", current.pid_by_group)
            if requested_mode == "fixed_different"
            else None
        ),
    }
    config = PushConfig.model_validate(merged)
    config_changed = bool(
        set(values).intersection(
            {"target_scope", "group_ids", "mode", "pid", "pid_by_group"}
        )
    )
    await _validate_groups(config, require_all_mapping=config_changed)

    # Persist the complete, mode-normalized configuration. This also clears
    # stale PID fields when switching between fixed and random modes.
    values["target_scope"] = config.target_scope
    values["group_ids"] = config.group_ids
    values["mode"] = config.mode
    values["pid"] = config.pid if config.mode == "fixed_same" else None
    values["pid_by_group"] = (
        config.pid_by_group if config.mode == "fixed_different" else None
    )
    if "due_at" in values and values["due_at"] is not None and values["due_at"].tzinfo is None:
        raise HTTPException(422, "due_at 必须包含时区")
    if "timezone" in values:
        try:
            ZoneInfo(str(values["timezone"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, "无效时区") from exc
    final_repeat = values.get("repeat", current.repeat)
    if final_repeat == "interval":
        interval = values.get("interval_seconds", current.interval_seconds)
        if interval is None:
            raise HTTPException(422, "固定间隔计划必须提供 interval_seconds")
        values["interval_seconds"] = interval
    else:
        values["interval_seconds"] = None
    try:
        plan = await image_push.update_plan(plan_id, values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _plan_response(plan, await _latest_batch(plan.id))


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str):
    if not await image_push.cancel_plan(plan_id):
        raise HTTPException(404, "推送计划不存在")
    return {"removed": True}


@router.post("/plans/{plan_id}/run", response_model=BatchResponse)
async def run_plan(plan_id: str):
    batch = await image_push.trigger_plan(plan_id)
    if batch is None:
        raise HTTPException(404, "推送计划不存在")
    return _batch_response(batch)


@router.post("/manual", response_model=BatchResponse)
async def manual_push(payload: ManualPayload):
    from .group_guard import bot

    bot()
    await _validate_groups(payload)
    batch = await image_push.create_batch(payload.model_dump(), trigger="manual")
    return _batch_response(batch)


@router.get("/batches", response_model=PageResponse)
async def get_batches(
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    plan_id: str | None = None, trigger: Literal["manual", "auto"] | None = None,
    state: str | None = None,
):
    total, batches = await image_push.list_batches(
        limit=page_size, offset=page_offset(page, page_size),
        plan_id=plan_id, trigger=trigger, state=state,
    )
    return PageResponse(
        items=[_batch_response(batch) for batch in batches],
        **page_meta(total, page, page_size).model_dump(),
    )


@router.get("/batches/{batch_id}", response_model=BatchResponse)
async def get_batch(batch_id: str):
    batch = await image_push.get_batch(batch_id)
    if batch is None:
        raise HTTPException(404, "推送批次不存在")
    return _batch_response(batch, await image_push.deliveries(batch_id))
