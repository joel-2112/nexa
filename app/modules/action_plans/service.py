"""Action plans service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import ActionPlan, ActionPlanStatus
from app.modules.action_plans.repository import ActionPlanRepository


class ActionPlanService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ActionPlanRepository(db)

    async def get(self, plan_id: uuid.UUID, user_id: uuid.UUID) -> ActionPlan:
        plan = await self.repo.get_by_id(plan_id, user_id)
        if not plan:
            raise NotFoundError("Action plan not found")
        return plan

    async def list_user_plans(
        self, user_id: uuid.UUID, status: ActionPlanStatus | None = None, limit: int = 20
    ) -> list[ActionPlan]:
        return await self.repo.list_by_user(user_id, status=status, limit=limit)

    async def approve_plan(self, plan_id: uuid.UUID, user_id: uuid.UUID) -> ActionPlan:
        plan = await self.repo.get_by_id(plan_id, user_id)
        if not plan:
            raise NotFoundError("Action plan not found")
        if plan.status != ActionPlanStatus.pending_approval:
            raise ValidationError(f"Plan cannot be approved in status '{plan.status.value}'")

        approved_plan = await self.repo.approve(plan_id, user_id)
        if not approved_plan:
            raise ValidationError("Failed to approve action plan")

        # Execute plan steps in background
        dispatched_celery = False
        try:
            from app.workers.tasks import execute_approved_plan

            execute_approved_plan.delay(str(plan_id), str(user_id))
            dispatched_celery = True
        except Exception:
            pass

        if not dispatched_celery:
            import asyncio

            from app.workers.tasks import execute_plan_async

            asyncio.create_task(execute_plan_async(str(plan_id), str(user_id)))

        return approved_plan

    async def reject_plan(self, plan_id: uuid.UUID, user_id: uuid.UUID, reason: str) -> ActionPlan:
        plan = await self.repo.get_by_id(plan_id, user_id)
        if not plan:
            raise NotFoundError("Action plan not found")
        if plan.status != ActionPlanStatus.pending_approval:
            raise ValidationError(f"Plan cannot be rejected in status '{plan.status.value}'")

        rejected_plan = await self.repo.reject(plan_id, user_id, reason)
        if not rejected_plan:
            raise ValidationError("Failed to reject action plan")
        return rejected_plan
