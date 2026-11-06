"""Notifications router."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.dependencies import CurrentUserId, DbSession
from app.modules.notifications.schemas import NotificationResponse
from app.modules.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    user_id: CurrentUserId,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[NotificationResponse]:
    svc = NotificationService(db)
    items = await svc.list_user_notifications(user_id, limit=limit)
    return [NotificationResponse.model_validate(n) for n in items]
