"""Contacts repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Contact


class ContactRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, contact_id: uuid.UUID, owner_id: uuid.UUID) -> Contact | None:
        result = await self.db.execute(select(Contact).where(Contact.id == contact_id, Contact.owner_id == owner_id))
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Contact], int]:
        query = select(Contact).where(Contact.owner_id == owner_id)
        count_query = select(func.count()).select_from(Contact).where(Contact.owner_id == owner_id)

        if search:
            pattern = f"%{search}%"
            query = query.where(Contact.full_name.ilike(pattern) | Contact.email.ilike(pattern))
            count_query = count_query.where(Contact.full_name.ilike(pattern) | Contact.email.ilike(pattern))

        query = query.order_by(Contact.full_name).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        count_result = await self.db.execute(count_query)
        return list(result.scalars().all()), count_result.scalar_one()

    async def create(
        self,
        owner_id: uuid.UUID,
        full_name: str,
        email: str | None,
        phone: str | None,
        company: str | None,
        notes: str | None,
    ) -> Contact:
        contact = Contact(
            owner_id=owner_id,
            full_name=full_name,
            email=email,
            phone=phone,
            company=company,
            notes=notes,
        )
        self.db.add(contact)
        await self.db.flush()
        return contact

    async def update(self, contact: Contact, **kwargs: object) -> Contact:
        for k, v in kwargs.items():
            setattr(contact, k, v)
        await self.db.flush()
        return contact

    async def delete(self, contact: Contact) -> None:
        await self.db.delete(contact)
        await self.db.flush()
