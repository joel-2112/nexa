"""Notifications service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationChannel, NotificationDelivery
from app.modules.notifications.repository import NotificationRepository


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = NotificationRepository(db)

    async def list_user_notifications(self, user_id: uuid.UUID, limit: int = 50) -> list[NotificationDelivery]:
        return await self.repo.list_by_user(user_id, limit=limit)

    async def create_notification(
        self,
        user_id: uuid.UUID,
        channel: NotificationChannel,
        body: str,
        subject: str | None = None,
        job_id: uuid.UUID | None = None,
    ) -> NotificationDelivery:
        return await self.repo.create(
            user_id=user_id,
            channel=channel,
            body=body,
            subject=subject,
            job_id=job_id,
        )
