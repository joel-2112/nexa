"""Conversations module schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import ConversationStatus, MessageRole


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=512)


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=16384)


class MessageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    tool_calls: list[dict] = []
    tool_name: str | None = None
    tokens_used: int | None = None
    created_at: datetime


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
    pending_questions: list[dict] = []
    collected_data: dict = {}


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    page: int
    size: int


class ChatTurnResponse(BaseModel):
    message: MessageResponse
    action_plan_id: UUID | None = None
    clarification_needed: bool = False
    follow_up_questions: list[str] = []
