"""Notifications repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationChannel, NotificationDelivery, NotificationStatus


class NotificationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        user_id: uuid.UUID,
        channel: NotificationChannel,
        body: str,
        subject: str | None = None,
        job_id: uuid.UUID | None = None,
    ) -> NotificationDelivery:
        notification = NotificationDelivery(
            user_id=user_id,
            channel=channel,
            subject=subject,
            body=body,
            job_id=job_id,
            status=NotificationStatus.pending,
        )
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def mark_sent(self, notification_id: uuid.UUID, external_id: str | None = None) -> None:
        await self.db.execute(
            update(NotificationDelivery)
            .where(NotificationDelivery.id == notification_id)
            .values(
                status=NotificationStatus.sent,
                sent_at=datetime.now(UTC),
                external_id=external_id,
            )
        )
        await self.db.flush()

    async def mark_failed(self, notification_id: uuid.UUID, error_message: str) -> None:
        await self.db.execute(
            update(NotificationDelivery)
            .where(NotificationDelivery.id == notification_id)
            .values(
                status=NotificationStatus.failed,
                error_message=error_message,
            )
        )
        await self.db.flush()

    async def list_by_user(self, user_id: uuid.UUID, limit: int = 50) -> list[NotificationDelivery]:
        result = await self.db.execute(
            select(NotificationDelivery)
            .where(NotificationDelivery.user_id == user_id)
            .order_by(NotificationDelivery.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
