"""Auth module Pydantic schemas."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    timezone: str = "Africa/Addis_Ababa"

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    email: str
    full_name: str
    timezone: str
    status: str
    is_superuser: bool
    telegram_id: int | None = None
    created_at: str

    @classmethod
    def from_orm(cls, user: object) -> UserResponse:
        u = user
        return cls(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            timezone=u.timezone,
            status=(
                u.status.value if hasattr(u.status, "value") else str(u.status)
            ),
            is_superuser=u.is_superuser,
            telegram_id=getattr(u, "telegram_id", None),
            created_at=(u.created_at.isoformat() if getattr(u, "created_at", None) else ""),
        )
