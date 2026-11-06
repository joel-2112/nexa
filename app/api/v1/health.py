"""Health check endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.core.config import settings
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
    }


@router.get("/health/ready", status_code=status.HTTP_200_OK)
async def readiness() -> dict[str, Any]:
    # Check PostgreSQL database connectivity
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database readiness probe failed: {exc}",
        )

    return {
        "status": "ready",
        "database": db_status,
        "google_configured": settings.google_configured,
        "telegram_configured": settings.telegram_configured,
        "n8n_configured": settings.n8n_configured,
    }
