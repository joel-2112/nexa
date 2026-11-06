"""Action plans router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import NotFoundError, ValidationError, http_bad_request, http_not_found
from app.db.models import ActionPlanStatus
from app.modules.action_plans.schemas import ActionPlanResponse, RejectPlanRequest
from app.modules.action_plans.service import ActionPlanService

router = APIRouter(prefix="/action-plans", tags=["action-plans"])


@router.get("", response_model=list[ActionPlanResponse])
async def list_action_plans(
    user_id: CurrentUserId,
    db: DbSession,
    status_filter: ActionPlanStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ActionPlanResponse]:
    svc = ActionPlanService(db)
    plans = await svc.list_user_plans(user_id, status=status_filter, limit=limit)
    return [ActionPlanResponse.model_validate(p) for p in plans]


@router.get("/{plan_id}", response_model=ActionPlanResponse)
async def get_action_plan(
    plan_id: UUID,
    user_id: CurrentUserId,
    db: DbSession,
) -> ActionPlanResponse:
    svc = ActionPlanService(db)
    try:
        plan = await svc.get(plan_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.message)
    return ActionPlanResponse.model_validate(plan)


@router.post("/{plan_id}/approve", response_model=ActionPlanResponse)
async def approve_action_plan(
    plan_id: UUID,
    user_id: CurrentUserId,
    db: DbSession,
) -> ActionPlanResponse:
    svc = ActionPlanService(db)
    try:
        plan = await svc.approve_plan(plan_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.message)
    except ValidationError as exc:
        raise http_bad_request(exc.message)
    return ActionPlanResponse.model_validate(plan)


@router.post("/{plan_id}/reject", response_model=ActionPlanResponse)
async def reject_action_plan(
    plan_id: UUID,
    body: RejectPlanRequest,
    user_id: CurrentUserId,
    db: DbSession,
) -> ActionPlanResponse:
    svc = ActionPlanService(db)
    try:
        plan = await svc.reject_plan(plan_id, user_id, body.reason)
    except NotFoundError as exc:
        raise http_not_found(exc.message)
    except ValidationError as exc:
        raise http_bad_request(exc.message)
    return ActionPlanResponse.model_validate(plan)
