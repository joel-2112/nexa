"""Notifications schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.db.models import NotificationChannel, NotificationStatus


class NotificationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    user_id: UUID
    job_id: UUID | None = None
    channel: NotificationChannel
    status: NotificationStatus
    subject: str | None = None
    body: str
    sent_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
