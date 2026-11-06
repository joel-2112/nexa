"""Action plans repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ActionPlan, ActionPlanStatus


class ActionPlanRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, plan_id: uuid.UUID, user_id: uuid.UUID) -> ActionPlan | None:
        result = await self.db.execute(
            select(ActionPlan)
            .where(ActionPlan.id == plan_id, ActionPlan.user_id == user_id)
            .options(selectinload(ActionPlan.steps))
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: uuid.UUID, status: ActionPlanStatus | None = None, limit: int = 20
    ) -> list[ActionPlan]:
        query = select(ActionPlan).where(ActionPlan.user_id == user_id)
        if status:
            query = query.where(ActionPlan.status == status)
        query = query.options(selectinload(ActionPlan.steps)).order_by(ActionPlan.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def approve(self, plan_id: uuid.UUID, user_id: uuid.UUID) -> ActionPlan | None:
        plan = await self.get_by_id(plan_id, user_id)
        if plan is None or plan.status != ActionPlanStatus.pending_approval:
            return None
        plan.status = ActionPlanStatus.approved
        plan.approved_at = datetime.now(UTC)
        await self.db.flush()
        return plan

    async def reject(self, plan_id: uuid.UUID, user_id: uuid.UUID, reason: str) -> ActionPlan | None:
        plan = await self.get_by_id(plan_id, user_id)
        if plan is None or plan.status != ActionPlanStatus.pending_approval:
            return None
        plan.status = ActionPlanStatus.rejected
        plan.rejected_at = datetime.now(UTC)
        plan.rejection_reason = reason
        await self.db.flush()
        return plan

    async def update_status(self, plan_id: uuid.UUID, status: ActionPlanStatus) -> None:
        values = {"status": status}
        if status == ActionPlanStatus.completed:
            values["completed_at"] = datetime.now(UTC)
        await self.db.execute(update(ActionPlan).where(ActionPlan.id == plan_id).values(**values))
        await self.db.flush()
