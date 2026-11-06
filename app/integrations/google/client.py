"""Google OAuth2 client and credential manager."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    IntegrationError,
    IntegrationNotConfiguredError,
    TokenExpiredError,
)
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import ConnectedAccount, IntegrationProvider
from google.oauth2.credentials import Credentials

logger = get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


class GoogleOAuthClient:
    def __init__(self) -> None:
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI
        self.scopes = settings.google_scopes_list

    def _ensure_configured(self) -> None:
        if not settings.google_configured:
            raise IntegrationNotConfiguredError(
                "Google OAuth credentials (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET) are not configured.",
                provider="google",
            )

    def build_authorization_url(self, state: str) -> str:
        self._ensure_configured()
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        self._ensure_configured()
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=data)
            if resp.status_code != 200:
                logger.error("google_token_exchange_failed", status=resp.status_code, body=resp.text)
                raise IntegrationError(
                    f"Failed to exchange Google OAuth code: {resp.text}",
                    provider="google",
                )
            return resp.json()

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                raise IntegrationError("Failed to fetch Google userinfo", provider="google")
            return resp.json()

    async def handle_callback(self, code: str, user_id: uuid.UUID, db: AsyncSession) -> dict[str, Any]:
        token_data = await self.exchange_code(code)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        userinfo = await self.fetch_userinfo(access_token)
        google_id = userinfo.get("id")
        email = userinfo.get("email")
        name = userinfo.get("name")

        # Save or update connected account
        stmt = select(ConnectedAccount).where(
            ConnectedAccount.user_id == user_id,
            ConnectedAccount.provider == IntegrationProvider.google,
        )
        res = await db.execute(stmt)
        account = res.scalar_one_or_none()

        encrypted_access = encrypt_secret(access_token) if access_token else None
        encrypted_refresh = encrypt_secret(refresh_token) if refresh_token else None

        if account:
            account.provider_account_id = str(google_id)
            account.email = email
            account.display_name = name
            account.encrypted_access_token = encrypted_access
            if encrypted_refresh:
                account.encrypted_refresh_token = encrypted_refresh
            account.token_expires_at = token_expires_at
            account.scopes = self.scopes
            account.is_active = True
        else:
            account = ConnectedAccount(
                user_id=user_id,
                provider=IntegrationProvider.google,
                provider_account_id=str(google_id),
                email=email,
                display_name=name,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                token_expires_at=token_expires_at,
                scopes=self.scopes,
                is_active=True,
            )
            db.add(account)

        await db.flush()
        return {"email": email, "name": name, "provider_account_id": google_id}

    async def get_credentials(self, user_id: uuid.UUID, db: AsyncSession) -> Credentials:
        self._ensure_configured()
        stmt = select(ConnectedAccount).where(
            ConnectedAccount.user_id == user_id,
            ConnectedAccount.provider == IntegrationProvider.google,
            ConnectedAccount.is_active.is_(True),
        )
        res = await db.execute(stmt)
        account = res.scalar_one_or_none()
        if not account or not account.encrypted_refresh_token:
            raise IntegrationError(
                "Google Workspace is not connected for this user.",
                provider="google",
            )

        refresh_token = decrypt_secret(account.encrypted_refresh_token)
        access_token = decrypt_secret(account.encrypted_access_token) if account.encrypted_access_token else None

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URL,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=account.scopes or self.scopes,
        )

        # Refresh if expired
        now = datetime.now(UTC)
        if not access_token or (account.token_expires_at and account.token_expires_at <= now):
            try:
                # httpx async refresh
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        GOOGLE_TOKEN_URL,
                        data={
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "refresh_token": refresh_token,
                            "grant_type": "refresh_token",
                        },
                    )
                    if resp.status_code == 200:
                        new_data = resp.json()
                        new_access = new_data["access_token"]
                        new_exp = datetime.now(UTC) + timedelta(seconds=new_data.get("expires_in", 3600))
                        account.encrypted_access_token = encrypt_secret(new_access)
                        account.token_expires_at = new_exp
                        await db.flush()
                        creds = Credentials(
                            token=new_access,
                            refresh_token=refresh_token,
                            token_uri=GOOGLE_TOKEN_URL,
                            client_id=self.client_id,
                            client_secret=self.client_secret,
                            scopes=account.scopes,
                        )
                    else:
                        raise TokenExpiredError(
                            "Google OAuth refresh token expired or revoked. Please reconnect.",
                            provider="google",
                        )
            except Exception as e:
                if isinstance(e, TokenExpiredError):
                    raise
                raise IntegrationError(f"Failed to refresh Google token: {e}", provider="google") from e

        return creds
