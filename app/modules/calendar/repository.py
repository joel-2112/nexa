"""Calendar repository."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import CalendarEvent, EventParticipant


class CalendarRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, event_id: uuid.UUID, owner_id: uuid.UUID) -> CalendarEvent | None:
        result = await self.db.execute(
            select(CalendarEvent)
            .where(CalendarEvent.id == event_id, CalendarEvent.owner_id == owner_id)
            .options(selectinload(CalendarEvent.participants))
        )
        return result.scalar_one_or_none()

    async def get_by_google_event_id(self, google_event_id: str) -> CalendarEvent | None:
        result = await self.db.execute(select(CalendarEvent).where(CalendarEvent.google_event_id == google_event_id))
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        start_from: datetime | None = None,
        start_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[CalendarEvent], int]:
        query = select(CalendarEvent).where(CalendarEvent.owner_id == owner_id)
        count_query = select(func.count()).select_from(CalendarEvent).where(CalendarEvent.owner_id == owner_id)

        if start_from:
            query = query.where(CalendarEvent.start_at >= start_from)
            count_query = count_query.where(CalendarEvent.start_at >= start_from)
        if start_to:
            query = query.where(CalendarEvent.start_at <= start_to)
            count_query = count_query.where(CalendarEvent.start_at <= start_to)

        query = (
            query.order_by(CalendarEvent.start_at)
            .options(selectinload(CalendarEvent.participants))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(query)
        count_result = await self.db.execute(count_query)
        return list(result.scalars().all()), count_result.scalar_one()

    async def create(
        self,
        owner_id: uuid.UUID,
        title: str,
        description: str | None,
        location: str | None,
        start_at: datetime,
        end_at: datetime,
        is_recurring: bool = False,
        recurrence_rule: str | None = None,
        source_conversation_id: uuid.UUID | None = None,
    ) -> CalendarEvent:
        event = CalendarEvent(
            owner_id=owner_id,
            title=title,
            description=description,
            location=location,
            start_at=start_at,
            end_at=end_at,
            is_recurring=is_recurring,
            recurrence_rule=recurrence_rule,
            source_conversation_id=source_conversation_id,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def add_participant(
        self,
        event_id: uuid.UUID,
        email: str,
        full_name: str | None,
        is_organizer: bool = False,
    ) -> EventParticipant:
        participant = EventParticipant(
            event_id=event_id,
            email=email,
            full_name=full_name,
            is_organizer=is_organizer,
        )
        self.db.add(participant)
        await self.db.flush()
        return participant

    async def update(self, event: CalendarEvent, **kwargs: object) -> CalendarEvent:
        for k, v in kwargs.items():
            setattr(event, k, v)
        await self.db.flush()
        return event

    async def delete(self, event: CalendarEvent) -> None:
        await self.db.delete(event)
        await self.db.flush()
