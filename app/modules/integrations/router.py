"""Integrations status and management router."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.core.config import settings
from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import (
    IntegrationError,
    http_bad_request,
    http_service_unavailable,
)
from app.core.logging import get_logger
from app.db.models import ConnectedAccount, IntegrationProvider, User
from app.integrations.google.client import GoogleOAuthClient
from app.modules.integrations.schemas import (
    GoogleAuthUrlResponse,
    IntegrationItem,
    IntegrationsStatusResponse,
    TelegramConnectResponse,
)

logger = get_logger(__name__)

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


@router.get("/google/connect-browser")
async def connect_google_browser(
    token: str = Query(..., description="User ID or access token"),
    db: DbSession = None,
) -> Response:
    """Browser-accessible Google OAuth entrypoint that redirects straight to Google."""
    from uuid import UUID

    from fastapi.responses import RedirectResponse

    from app.core.security import decode_token
    from app.db.models import User

    target_user_id = None
    try:
        # Check if JWT token
        payload = decode_token(token)
        target_user_id = payload.get("sub")
    except Exception:
        # Check if raw User UUID
        try:
            u_id = UUID(token)
            stmt = select(User).where(User.id == u_id)
            user_rec = (await db.execute(stmt)).scalar_one_or_none()
            if user_rec:
                target_user_id = str(user_rec.id)
        except Exception:
            pass

    if not target_user_id:
        raise http_bad_request("Invalid or expired authentication token for Google connect.")

    if not settings.google_configured:
        raise http_service_unavailable(
            "Google integration is not configured. Please supply GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )

    client = GoogleOAuthClient()
    state = f"{target_user_id}:{secrets.token_urlsafe(16)}"
    url = client.build_authorization_url(state=state)
    return RedirectResponse(url=url)


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
) -> Response:
    from fastapi.responses import HTMLResponse

    from app.db.models import User

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

    connected_email = account_info.get("email", "your Google account")

    # Notify user on Telegram if connected
    try:
        stmt = select(User).where(User.id == user_id)
        u = (await db.execute(stmt)).scalar_one_or_none()
        if u and u.telegram_id:
            from app.integrations.telegram.bot import TelegramBotService

            bot = TelegramBotService()
            await bot.send_message(
                chat_id=u.telegram_id,
                text=(
                    f"🎉 <b>Google Workspace Connected!</b>\n\n"
                    f"Successfully connected: <code>{connected_email}</code>\n"
                    "Your Google Calendar, Meet links, and Gmail invitations are now active.\n\n"
                    "Type /dashboard to see your updated status!"
                ),
            )
    except Exception as e:
        logger.warning("telegram_google_connect_notify_failed", error=str(e))

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Google Workspace Connected</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex; align-items: center; justify-content: center;
                height: 100vh; margin: 0; background: #0b0f19; color: #f8fafc; text-align: center;
            }}
            .card {{
                background: #1e293b; padding: 2.5rem 2rem; border-radius: 1rem;
                border: 1px solid #334155; max-width: 400px; margin: 1rem;
                box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
            }}
            h1 {{ color: #22c55e; margin: 0 0 0.75rem; font-size: 1.5rem; }}
            p {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.6; margin: 0.5rem 0; }}
            .email {{ color: #38bdf8; font-weight: 600; }}
            .btn {{
                display: inline-block; margin-top: 1.5rem; background: #2563eb; color: #ffffff;
                padding: 0.75rem 1.75rem; border-radius: 0.5rem; text-decoration: none;
                font-weight: 600; font-size: 0.95rem;
            }}
            .btn:hover {{ background: #1d4ed8; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>✅ Google Connected!</h1>
            <p>Your Google Workspace account (<span class="email">{connected_email}</span>) is now linked to NEXA.</p>
            <p>Google Calendar, Meet links, and reminders are fully active. You can now return to Telegram.</p>
            <a class="btn" href="https://t.me/Nexa_AI_Assistant_bot">Return to Telegram</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


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
