"""Administrative guard API. Deployment gateway authenticates /api and /admin."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from telegram.error import TelegramError

from models import (
    Group,
    GroupGuardPendingVerification,
    GuardEvent,
    GuardRecord,
    GuardTask,
)
from registries import engine
from services.moderation import actions, reviews, store, worker
from services import group_members
from services.moderation.schemas import (
    ActionRequest,
    AIConfig,
    Content,
    OperationResult,
    Policy,
    PolicyPatch,
    ReviewDecision,
    Rule,
    validate_record_name,
)


async def ensure_group(group_id: int):
    async with engine.new_session() as session:
        if not await session.get(Group, group_id):
            raise HTTPException(404, "群组不存在")


router = APIRouter(
    prefix="/api/groups/{group_id}/guard",
    tags=["group-guard"],
    dependencies=[Depends(ensure_group)],
)
model_router = APIRouter(prefix="/api/guard-ai", tags=["group-guard-ai"])


class GroupMemberListItem(BaseModel):
    """A member observed by the bot in this group."""

    model_config = ConfigDict(use_enum_values=True)

    user_id: int
    display_name: str | None
    username: str | None
    role: Literal["admin", "member"]
    source: list[Literal["message", "admin", "moderation"]]
    message_count: int
    last_activity: datetime | None
    warning_count: int
    restriction_active: bool
    exempt: bool
    verification_state: str | None


class GroupMemberListResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    total: int
    items: list[GroupMemberListItem]
    page: int
    page_size: int
    pages: int
    coverage: Literal["observed"]
    telegram_member_count: int | None


def bot():
    from bot import tg_bot

    if not tg_bot.tg_bot:
        raise HTTPException(409, "Telegram 机器人尚未连接")
    return tg_bot.tg_bot


@router.get("", response_model=Policy)
async def get_policy(group_id: int):
    return await store.policy(group_id)


@router.patch("", response_model=Policy)
async def patch_policy(group_id: int, payload: PolicyPatch):
    changes = payload.model_dump(exclude_unset=True)
    try:
        result = await store.save_policy(group_id, changes)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    await store.event(
        group_id,
        "configuration",
        source="web:deployment-admin",
        data={"fields": list(changes)},
    )
    return result


@router.get("/meta")
async def metadata(group_id: int):
    return {
        "schema": Policy.model_json_schema(),
        "rule_kinds": ["keyword", "regex", "link", "invite", "forward", "media"],
    }


@router.get("/permissions")
async def permissions(group_id: int):
    tg = bot()
    try:
        member = await tg.get_chat_member(group_id, tg.id)
        return {
            "status": member.status,
            **{
                k: bool(getattr(member, k, False))
                for k in (
                    "can_delete_messages",
                    "can_restrict_members",
                    "can_invite_users",
                    "can_pin_messages",
                )
            },
        }
    except TelegramError as exc:
        raise HTTPException(502, type(exc).__name__) from exc


@router.get("/rules")
async def list_rules(group_id: int):
    from dataclasses import asdict

    from services import group_guard

    return {
        "items": await store.records(group_id, "rule"),
        "legacy": [asdict(r) for r in await group_guard.list_keyword_rules(group_id)],
    }


@router.put("/rules/{rule_id}")
async def put_rule(group_id: int, rule_id: str, payload: Rule):
    try:
        rule_id = validate_record_name(rule_id, "规则名称")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await store.put_record(
        group_id, "rule", rule_id, payload.model_dump(), payload.enabled
    )


@router.delete("/rules/{rule_id}")
async def delete_rule(group_id: int, rule_id: str):
    return {"removed": await store.remove_record(group_id, "rule", rule_id)}


@router.delete("/legacy-rules/{rule_id}")
async def delete_legacy(group_id: int, rule_id: int):
    from services import group_guard

    return {"removed": await group_guard.remove_keyword_rule(group_id, rule_id)}


@router.get("/members", response_model=GroupMemberListResponse)
async def list_members(
    group_id: int,
    q: str | None = Query(default=None, description="按用户 ID、用户名或显示名搜索"),
    role: Literal["admin", "member"] | None = Query(default=None),
    state: Literal["warned", "restricted", "exempt"] | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    sort_by: Literal["id", "display_name", "message_count", "last_activity"] = Query(
        default="last_activity"
    ),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
) -> GroupMemberListResponse:
    """List members known to this bot without claiming Telegram full coverage."""

    result = await group_members.list_observed_members(
        group_id,
        q=q,
        role=role,
        state=state,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    telegram_member_count: int | None = None
    try:
        value = await bot().get_chat_member_count(group_id)
        if isinstance(value, int):
            telegram_member_count = value
    except (HTTPException, TelegramError):
        # A member directory remains useful when Telegram is disconnected or
        # temporarily unavailable.  The UI will hide the optional count.
        pass

    return GroupMemberListResponse(
        **result,
        coverage="observed",
        telegram_member_count=telegram_member_count,
    )


@router.get("/members/{user_id}")
async def member(group_id: int, user_id: int):
    async with engine.new_session() as session:
        pending = await session.get(GroupGuardPendingVerification, (group_id, user_id))
        verification = (
            {
                k: v
                for k, v in store.dump(pending).items()
                if k not in {"token", "answer"}
            }
            if pending
            else None
        )
    bot_approval = await store.record(group_id, "bot_approval", str(user_id))
    return {
        "user_id": user_id,
        "warnings": await store.warnings(group_id, user_id),
        "restriction": await store.record(group_id, "restriction", str(user_id)),
        "exempt": bool(await store.record(group_id, "exempt", str(user_id))),
        "verification": verification,
        "bot_approval": bot_approval,
    }


@router.put("/members/{user_id}/exempt")
async def exempt(group_id: int, user_id: int, enabled: bool = True):
    if user_id <= 0:
        raise HTTPException(422, "无效成员 ID")
    if enabled:
        await store.put_record(group_id, "exempt", str(user_id), {})
    else:
        await store.remove_record(group_id, "exempt", str(user_id))
    return {"exempt": enabled}


@router.post("/actions", response_model=OperationResult)
async def action(group_id: int, payload: ActionRequest):
    try:
        result = await actions.execute(bot(), group_id, payload)
        return {key: result[key] for key in OperationResult.model_fields}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except TelegramError as exc:
        raise HTTPException(502, type(exc).__name__) from exc


@router.get("/contents")
async def contents(group_id: int):
    return {
        kind: await store.records(group_id, kind)
        for kind in ("reply", "note", "announcement")
    }


@router.post("/events/{event_id}/revoke")
async def revoke_event(group_id: int, event_id: str):
    try:
        return await actions.revoke_warning(bot(), group_id, event_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/contents")
async def put_content(group_id: int, payload: Content):
    return await worker.save_content(group_id, payload)


@router.delete("/contents/{kind}/{name}")
async def delete_content(
    group_id: int, kind: Literal["reply", "note", "announcement"], name: str
):
    return {"removed": await worker.delete_content(group_id, kind, name)}


async def page(model, group_id, page_number, page_size, *where):
    async with engine.new_session() as session:
        conditions = (model.group_id == group_id, *where)
        total = await session.scalar(
            select(func.count()).select_from(model).where(*conditions)
        )
        rows = (
            await session.scalars(
                select(model)
                .where(*conditions)
                .order_by(model.created_at.desc(), model.id.desc())
                .offset((page_number - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    return {
        "items": [store.dump(row) for row in rows],
        "total": total,
        "page": page_number,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/reviews")
async def list_reviews(
    group_id: int,
    page_number: int = Query(1, alias="page", ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return await page(
        GuardRecord, group_id, page_number, page_size, GuardRecord.kind == "review"
    )


@router.post("/reviews/{review_id}")
async def decide_review(group_id: int, review_id: str, payload: ReviewDecision):
    try:
        return await reviews.decide(
            bot(), group_id, review_id, payload.decision, payload.reason
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/logs")
async def logs(
    group_id: int,
    page_number: int = Query(1, alias="page", ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    user_id: int | None = None,
):
    where = []
    if status:
        where.append(GuardEvent.status == status)
    if user_id is not None:
        where.append(GuardEvent.user_id == user_id)
    return await page(GuardEvent, group_id, page_number, page_size, *where)


@router.get("/tasks")
async def tasks(
    group_id: int,
    page_number: int = Query(1, alias="page", ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    result = await page(GuardTask, group_id, page_number, page_size)
    # Raw queued messages are not needed in the task list.
    for item in result["items"]:
        item["data"] = {
            k: v for k, v in item["data"].items() if k not in {"message", "policy"}
        }
    return result


@router.get("/stats")
async def stats(group_id: int):
    async with engine.new_session() as session:
        events = (
            await session.scalars(
                select(GuardEvent).where(
                    GuardEvent.group_id == group_id,
                    GuardEvent.created_at >= store.now() - timedelta(days=30),
                )
            )
        ).all()
    days = defaultdict(Counter)
    tokens = 0
    for event in events:
        days[event.created_at.date().isoformat()][event.action] += 1
        tokens += event.data.get("usage", {}).get("total_tokens", 0)
    return {
        "days": [{"date": key, "counts": value} for key, value in sorted(days.items())],
        "actions": Counter(e.action for e in events),
        "statuses": Counter(e.status for e in events),
        "total_tokens": tokens,
    }


@model_router.get("")
async def get_ai():
    return store.public_ai_config(await store.ai_config())


@model_router.put("")
async def put_ai(payload: AIConfig):
    return await store.save_ai_config(payload)
