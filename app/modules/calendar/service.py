"""Calendar service layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.modules.calendar.repository import CalendarRepository
from app.modules.calendar.schemas import (
    CalendarEventCreate,
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventUpdate,
)


class CalendarService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CalendarRepository(db)

    async def create_event(self, owner_id: uuid.UUID, payload: CalendarEventCreate) -> CalendarEventResponse:
        if payload.end_at <= payload.start_at:
            raise ValidationError("end_at must be after start_at")

        event = await self.repo.create(
            owner_id=owner_id,
            title=payload.title,
            description=payload.description,
            location=payload.location,
            start_at=payload.start_at,
            end_at=payload.end_at,
            is_recurring=payload.is_recurring,
            recurrence_rule=payload.recurrence_rule,
        )

        for p in payload.participants:
            await self.repo.add_participant(
                event_id=event.id,
                email=str(p.email),
                full_name=p.full_name,
                is_organizer=p.is_organizer,
            )

        # Reload with participants
        event = await self.repo.get_by_id(event.id, owner_id)
        assert event is not None
        return CalendarEventResponse.model_validate(event)

    async def list_events(
        self,
        owner_id: uuid.UUID,
        start_from: datetime | None = None,
        start_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> CalendarEventListResponse:
        events, total = await self.repo.list_for_user(owner_id, start_from, start_to, page, page_size)
        return CalendarEventListResponse(
            items=[CalendarEventResponse.model_validate(e) for e in events],
            total=total,
        )

    async def get_event(self, event_id: uuid.UUID, owner_id: uuid.UUID) -> CalendarEventResponse:
        event = await self.repo.get_by_id(event_id, owner_id)
        if event is None:
            raise NotFoundError("Calendar event not found")
        return CalendarEventResponse.model_validate(event)

    async def update_event(
        self, event_id: uuid.UUID, owner_id: uuid.UUID, payload: CalendarEventUpdate
    ) -> CalendarEventResponse:
        event = await self.repo.get_by_id(event_id, owner_id)
        if event is None:
            raise NotFoundError("Calendar event not found")
        updates = payload.model_dump(exclude_unset=True)
        event = await self.repo.update(event, **updates)
        return CalendarEventResponse.model_validate(event)

    async def delete_event(self, event_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        event = await self.repo.get_by_id(event_id, owner_id)
        if event is None:
            raise NotFoundError("Calendar event not found")
        await self.repo.delete(event)
