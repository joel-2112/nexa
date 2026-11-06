"""Auth service layer."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    verify_password,
)
from app.modules.auth.repository import RefreshTokenRepository, UserRepository
from app.modules.auth.schemas import TokenResponse


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_repo = UserRepository(db)
        self.token_repo = RefreshTokenRepository(db)

    async def register(self, email: str, password: str, full_name: str, timezone: str) -> object:
        existing = await self.user_repo.get_by_email(email)
        if existing is not None:
            raise ConflictError("A user with this email already exists")
        user = await self.user_repo.create(email, password, full_name, timezone)
        return user

    async def login(
        self,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenResponse:
        user = await self.user_repo.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise AuthenticationError("Incorrect email or password")
        return await self._issue_tokens(str(user.id), user_agent, ip_address)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        try:
            payload = decode_refresh_token(refresh_token)
        except AuthenticationError:
            raise

        jti = payload["jti"]
        rt = await self.token_repo.verify(jti, refresh_token)
        if rt is None:
            raise AuthenticationError("Refresh token is invalid or has been revoked")

        # Rotate: revoke old, issue new
        await self.token_repo.revoke(rt)
        return await self._issue_tokens(payload["sub"])

    async def logout(self, refresh_token: str) -> None:
        try:
            payload = decode_refresh_token(refresh_token)
            rt = await self.token_repo.get_by_jti(payload["jti"])
            if rt and not rt.revoked:
                await self.token_repo.revoke(rt)
        except Exception:
            pass  # logout is idempotent

    async def logout_all(self, user_id: uuid.UUID) -> None:
        await self.token_repo.revoke_all_for_user(user_id)

    async def _issue_tokens(
        self,
        user_id: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenResponse:
        jti = secrets.token_hex(32)
        expires_at = datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

        raw_refresh = create_refresh_token(user_id, jti)
        await self.token_repo.create(
            user_id=uuid.UUID(user_id),
            jti=jti,
            raw_token=raw_refresh,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        access_token = create_access_token(user_id)
        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
