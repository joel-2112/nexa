"""AI module Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import ActionPlanStatus, ConversationStatus, MessageRole


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8192)
    conversation_id: UUID | None = None


class MessageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    tool_calls: list[dict] = []
    tokens_used: int | None = None
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: UUID
    message: MessageResponse
    action_plan: ActionPlanResponse | None = None
    clarification_needed: bool = False
    clarification_question: str | None = None


class ConversationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    user_id: UUID
    title: str | None
    status: ConversationStatus
    message_count: int
    current_intent: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse] = []


class ActionStepResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    step_order: int
    tool_name: str
    description: str
    status: str
    arguments: dict
    result: dict
    error_message: str | None
    requires_approval: bool


class ActionPlanResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    user_id: UUID
    conversation_id: UUID | None
    title: str
    description: str | None
    intent: str
    status: ActionPlanStatus
    steps: list[ActionStepResponse] = []
    plan_data: dict
    result_data: dict
    created_at: datetime
    updated_at: datetime


class ApproveActionRequest(BaseModel):
    approved: bool
    rejection_reason: str | None = None


# Update forward reference
ChatResponse.model_rebuild()
