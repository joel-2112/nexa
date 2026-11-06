"""Telegram webhook router."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import settings
from app.core.dependencies import DbSession
from app.core.logging import get_logger
from app.integrations.telegram.bot import TelegramBotService

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations/telegram", tags=["telegram"])


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    db: DbSession,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    if not settings.telegram_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram integration is not configured",
        )

    # Validate secret header if configured
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            logger.warning("invalid_telegram_webhook_secret")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid secret token",
            )

    body = await request.json()
    bot_service = TelegramBotService()
    await bot_service.handle_update(body, db)
    return {"status": "ok"}
