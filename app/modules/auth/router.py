"""Auth API router."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    http_conflict,
    http_unauthorized,
)
from app.core.logging import get_logger
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.modules.auth.service import AuthService

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> UserResponse:
    """Register a new user account."""
    svc = AuthService(db)
    try:
        user = await svc.register(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            timezone=payload.timezone,
        )
    except ConflictError as exc:
        raise http_conflict(exc.detail)
    logger.info("user_registered", email=payload.email)
    return UserResponse.from_orm(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenResponse:
    """Authenticate and obtain access + refresh tokens."""
    svc = AuthService(db)
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    try:
        tokens = await svc.login(
            email=payload.email,
            password=payload.password,
            user_agent=user_agent,
            ip_address=ip_address,
        )
    except AuthenticationError as exc:
        raise http_unauthorized(exc.detail)
    logger.info("user_logged_in", email=payload.email)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    """Rotate refresh token and return new access + refresh pair."""
    svc = AuthService(db)
    try:
        tokens = await svc.refresh(payload.refresh_token)
    except AuthenticationError as exc:
        raise http_unauthorized(exc.detail)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, db: DbSession) -> None:
    """Revoke the given refresh token."""
    svc = AuthService(db)
    await svc.logout(payload.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user_id: CurrentUserId, db: DbSession) -> None:
    """Revoke all refresh tokens for the current user."""
    svc = AuthService(db)
    await svc.logout_all(user_id)


@router.get("/me", response_model=UserResponse)
async def get_me(user_id: CurrentUserId, db: DbSession) -> UserResponse:
    """Return the authenticated user's profile."""
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise http_unauthorized("User not found")
    return UserResponse.from_orm(user)
