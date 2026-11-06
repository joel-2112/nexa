"""Users module schemas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class UpdateUserRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)
    preferences: dict[str, Any] | None = None


class UserProfileResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    email: str
    full_name: str
    timezone: str
    status: str
    is_superuser: bool
    telegram_id: int | None = None
    preferences: dict[str, Any] = {}
