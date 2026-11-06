"""Integrations schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IntegrationItem(BaseModel):
    provider: str
    name: str
    configured_in_env: bool
    account_connected: bool
    account_email: str | None = None
    account_display_name: str | None = None
    connected_at: datetime | None = None
    scopes: list[str] = []


class IntegrationsStatusResponse(BaseModel):
    integrations: list[IntegrationItem]


class GoogleAuthUrlResponse(BaseModel):
    authorization_url: str
    state: str


class TelegramConnectResponse(BaseModel):
    bot_username: str | None = None
    deep_link: str
    link_token: str
    instructions: str
