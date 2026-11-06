"""AI schemas and data models."""

from __future__ import annotations

import enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IntentType(str, enum.Enum):
    SCHEDULE_MEETING = "schedule_meeting"
    CREATE_TASK = "create_task"
    LIST_TASKS = "list_tasks"
    COMPLETE_TASK = "complete_task"
    CHECK_CALENDAR = "check_calendar"
    SEND_EMAIL = "send_email"
    SEARCH_CONTACTS = "search_contacts"
    CREATE_CONTACT = "create_contact"
    GENERAL_QUERY = "general_query"
    UNKNOWN = "unknown"


class ExtractedIntent(BaseModel):
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    suggested_follow_up: str | None = None


class PlanStepDefinition(BaseModel):
    step_order: int
    tool_name: str
    description: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = True


class ExecutionPlanDefinition(BaseModel):
    title: str
    description: str
    intent: str
    steps: list[PlanStepDefinition] = Field(default_factory=list)
    plan_data: dict[str, Any] = Field(default_factory=dict)


class ToolCallInfo(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any]


class OrchestratorResponse(BaseModel):
    response_text: str
    action_plan_id: UUID | None = None
    clarification_needed: bool = False
    follow_up_questions: list[str] = Field(default_factory=list)
    executed_tools: list[dict[str, Any]] = Field(default_factory=list)
