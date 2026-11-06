"""Contacts service layer."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
)


class ContactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ContactRepository(db)

    async def create_contact(self, owner_id: uuid.UUID, payload: ContactCreate) -> ContactResponse:
        contact = await self.repo.create(
            owner_id=owner_id,
            full_name=payload.full_name,
            email=str(payload.email) if payload.email else None,
            phone=payload.phone,
            company=payload.company,
            notes=payload.notes,
        )
        return ContactResponse.model_validate(contact)

    async def list_contacts(
        self,
        owner_id: uuid.UUID,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ContactListResponse:
        contacts, total = await self.repo.list_for_user(owner_id, search, page, page_size)
        return ContactListResponse(
            items=[ContactResponse.model_validate(c) for c in contacts],
            total=total,
        )

    async def get_contact(self, contact_id: uuid.UUID, owner_id: uuid.UUID) -> ContactResponse:
        contact = await self.repo.get_by_id(contact_id, owner_id)
        if contact is None:
            raise NotFoundError("Contact not found")
        return ContactResponse.model_validate(contact)

    async def update_contact(
        self, contact_id: uuid.UUID, owner_id: uuid.UUID, payload: ContactUpdate
    ) -> ContactResponse:
        contact = await self.repo.get_by_id(contact_id, owner_id)
        if contact is None:
            raise NotFoundError("Contact not found")
        updates = payload.model_dump(exclude_unset=True)
        if "email" in updates and updates["email"] is not None:
            updates["email"] = str(updates["email"])
        contact = await self.repo.update(contact, **updates)
        return ContactResponse.model_validate(contact)

    async def delete_contact(self, contact_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        contact = await self.repo.get_by_id(contact_id, owner_id)
        if contact is None:
            raise NotFoundError("Contact not found")
        await self.repo.delete(contact)
