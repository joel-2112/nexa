"""Calendar module Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.db.models import CalendarEventStatus, ParticipantStatus


class ParticipantCreate(BaseModel):
    email: EmailStr
    full_name: str | None = None
    is_organizer: bool = False


class ParticipantResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    email: str
    full_name: str | None
    status: ParticipantStatus
    is_organizer: bool
    invitation_sent: bool


class CalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    description: str | None = None
    location: str | None = None
    start_at: datetime
    end_at: datetime
    participants: list[ParticipantCreate] = []
    is_recurring: bool = False
    recurrence_rule: str | None = None

    def model_post_init(self, __context: object) -> None:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")


class CalendarEventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = None
    location: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    status: CalendarEventStatus | None = None


class CalendarEventResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    owner_id: UUID
    title: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    status: CalendarEventStatus
    google_event_id: str | None
    meet_link: str | None
    is_recurring: bool
    participants: list[ParticipantResponse] = []
    created_at: datetime
    updated_at: datetime


class CalendarEventListResponse(BaseModel):
    items: list[CalendarEventResponse]
    total: int
