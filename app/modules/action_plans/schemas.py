"""Action plans module schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import ActionPlanStatus, ActionStepStatus


class ActionStepResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    step_order: int
    tool_name: str
    description: str
    status: ActionStepStatus
    arguments: dict = {}
    result: dict = {}
    error_message: str | None = None
    requires_approval: bool
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ActionPlanResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    user_id: UUID
    conversation_id: UUID | None = None
    title: str
    description: str | None = None
    intent: str
    status: ActionPlanStatus
    steps: list[ActionStepResponse] = []
    plan_data: dict = {}
    result_data: dict = {}
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RejectPlanRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1024)
