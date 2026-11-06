"""Contacts API router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import NotFoundError, http_not_found
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
)
from app.modules.contacts.service import ContactService

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(payload: ContactCreate, user_id: CurrentUserId, db: DbSession) -> ContactResponse:
    svc = ContactService(db)
    return await svc.create_contact(user_id, payload)


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    user_id: CurrentUserId,
    db: DbSession,
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ContactListResponse:
    svc = ContactService(db)
    return await svc.list_contacts(user_id, search, page, page_size)


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(contact_id: UUID, user_id: CurrentUserId, db: DbSession) -> ContactResponse:
    svc = ContactService(db)
    try:
        return await svc.get_contact(contact_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: UUID, payload: ContactUpdate, user_id: CurrentUserId, db: DbSession
) -> ContactResponse:
    svc = ContactService(db)
    try:
        return await svc.update_contact(contact_id, user_id, payload)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_contact(contact_id: UUID, user_id: CurrentUserId, db: DbSession) -> Response:
    svc = ContactService(db)
    try:
        await svc.delete_contact(contact_id, user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)
