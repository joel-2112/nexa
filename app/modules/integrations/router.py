"""Integrations status and management router."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.config import settings
from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import (
    IntegrationError,
    http_bad_request,
    http_service_unavailable,
)
from app.db.models import ConnectedAccount, IntegrationProvider, User
from app.integrations.google.client import GoogleOAuthClient
from app.modules.integrations.schemas import (
    GoogleAuthUrlResponse,
    IntegrationItem,
    IntegrationsStatusResponse,
    TelegramConnectResponse,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=IntegrationsStatusResponse)
async def get_integrations_status(
    user_id: CurrentUserId,
    db: DbSession,
) -> IntegrationsStatusResponse:
    # Query user connected accounts
    stmt = select(ConnectedAccount).where(ConnectedAccount.user_id == user_id)
    result = await db.execute(stmt)
    accounts = {acc.provider: acc for acc in result.scalars().all()}

    google_acc = accounts.get(IntegrationProvider.google)
    telegram_acc = accounts.get(IntegrationProvider.telegram)

    # Check telegram linked on User model as well
    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    telegram_connected = bool(telegram_acc or (user and user.telegram_id is not None))

    items = [
        IntegrationItem(
            provider="google",
            name="Google Workspace (Calendar, Gmail, Tasks)",
            configured_in_env=settings.google_configured,
            account_connected=bool(google_acc and google_acc.is_active),
            account_email=google_acc.email if google_acc else None,
            account_display_name=google_acc.display_name if google_acc else None,
            connected_at=google_acc.created_at if google_acc else None,
            scopes=google_acc.scopes if google_acc else [],
        ),
        IntegrationItem(
            provider="telegram",
            name="Telegram Bot Assistant",
            configured_in_env=settings.telegram_configured,
            account_connected=telegram_connected,
            account_display_name=str(user.telegram_id) if user and user.telegram_id else None,
            connected_at=user.updated_at if user and user.telegram_id else None,
            scopes=["bot_chat", "notifications"],
        ),
        IntegrationItem(
            provider="n8n",
            name="n8n Workflow Automation",
            configured_in_env=settings.n8n_configured,
            account_connected=settings.n8n_configured,
            scopes=["webhooks", "workflow_execution"],
        ),
    ]

    return IntegrationsStatusResponse(integrations=items)


@router.post("/google/connect", response_model=GoogleAuthUrlResponse)
async def connect_google(user_id: CurrentUserId) -> GoogleAuthUrlResponse:
    if not settings.google_configured:
        raise http_service_unavailable(
            "Google integration is not configured. Please supply GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )
    client = GoogleOAuthClient()
    # State embeds user_id for secure correlation
    state = f"{user_id}:{secrets.token_urlsafe(16)}"
    url = client.build_authorization_url(state=state)
    return GoogleAuthUrlResponse(authorization_url=url, state=state)


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: DbSession = None,
) -> dict:
    if not settings.google_configured:
        raise http_service_unavailable("Google integration is not configured.")

    client = GoogleOAuthClient()
    try:
        user_id_str = state.split(":")[0]
        from uuid import UUID

        user_id = UUID(user_id_str)
    except Exception:
        raise http_bad_request("Invalid OAuth state parameter")

    try:
        account_info = await client.handle_callback(code=code, user_id=user_id, db=db)
    except IntegrationError as exc:
        raise http_bad_request(f"OAuth failed: {exc.detail}")

    return {
        "status": "connected",
        "provider": "google",
        "email": account_info.get("email"),
        "message": "Google Workspace connected successfully.",
    }


@router.post("/telegram/connect", response_model=TelegramConnectResponse)
async def connect_telegram(
    user_id: CurrentUserId,
    db: DbSession,
) -> TelegramConnectResponse:
    if not settings.telegram_configured:
        raise http_service_unavailable("Telegram integration is not configured. Please supply TELEGRAM_BOT_TOKEN.")

    # Generate secure link token and save to User
    token = f"nexa_{secrets.token_urlsafe(24)}"
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        user.telegram_link_token = token
        await db.flush()

    bot_username = "NexaAssistantBot"
    deep_link = f"https://t.me/{bot_username}?start={token}"

    return TelegramConnectResponse(
        bot_username=bot_username,
        deep_link=deep_link,
        link_token=token,
        instructions=(
            f"Open Telegram, start a chat with @{bot_username}, and send `/start {token}` "
            "to securely link your account."
        ),
    )
