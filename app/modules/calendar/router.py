"""Calendar API router."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import NotFoundError, ValidationError, http_bad_request, http_not_found
from app.modules.calendar.schemas import (
    CalendarEventCreate,
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventUpdate,
)
from app.modules.calendar.service import CalendarService

router = APIRouter(prefix="/calendar", tags=["Calendar"])


@router.post("", response_model=CalendarEventResponse, status_code=status.HTTP_201_CREATED)
@router.post("/events", response_model=CalendarEventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(payload: CalendarEventCreate, user_id: CurrentUserId, db: DbSession) -> CalendarEventResponse:
    svc = CalendarService(db)
    try:
        return await svc.create_event(user_id, payload)
    except ValidationError as exc:
        raise http_bad_request(exc.detail)


@router.get("", response_model=CalendarEventListResponse)
@router.get("/events")
async def list_events(
    user_id: CurrentUserId,
    db: DbSession,
    start_from: datetime | None = Query(default=None, alias="start_from"),
    start_to: datetime | None = Query(default=None, alias="start_to"),
    start_min: datetime | None = Query(default=None, alias="start_min"),
    start_max: datetime | None = Query(default=None, alias="start_max"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CalendarEventListResponse:
    svc = CalendarService(db)
    effective_from = start_from or start_min
    effective_to = start_to or start_max
    return await svc.list_events(user_id, effective_from, effective_to, page, page_size)


@router.get("/{event_id}", response_model=CalendarEventResponse)
@router.get("/events/{event_id}", response_model=CalendarEventResponse)
async def get_event(event_id: UUID, user_id: CurrentUserId, db: DbSession) -> CalendarEventResponse:
    svc = CalendarService(db)
    try:
        return await svc.get_event(event_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)


@router.patch("/{event_id}", response_model=CalendarEventResponse)
@router.patch("/events/{event_id}", response_model=CalendarEventResponse)
async def update_event(
    event_id: UUID, payload: CalendarEventUpdate, user_id: CurrentUserId, db: DbSession
) -> CalendarEventResponse:
    svc = CalendarService(db)
    try:
        return await svc.update_event(event_id, user_id, payload)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: UUID, user_id: CurrentUserId, db: DbSession) -> None:
    svc = CalendarService(db)
    try:
        await svc.delete_event(event_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)
