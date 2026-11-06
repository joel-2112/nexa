"""Conversations repository."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Conversation, ConversationStatus, Message, MessageRole


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, user_id: uuid.UUID, title: str | None = None) -> Conversation:
        conv = Conversation(user_id=user_id, title=title)
        self.db.add(conv)
        await self.db.flush()
        return conv

    async def get_by_id(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .options(selectinload(Conversation.messages))
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_messages(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .options(selectinload(Conversation.messages))
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID, page: int = 1, size: int = 20) -> tuple[list[Conversation], int]:
        offset = (page - 1) * size
        count_result = await self.db.execute(
            select(func.count()).where(
                Conversation.user_id == user_id,
                Conversation.status != ConversationStatus.archived,
            )
        )
        total = count_result.scalar_one()

        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.status != ConversationStatus.archived,
            )
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(size)
        )
        return list(result.scalars().all()), total

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tokens_used: int | None = None,
        ai_metadata: dict[str, Any] | None = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls or [],
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tokens_used=tokens_used,
            ai_metadata=ai_metadata or {},
        )
        self.db.add(msg)

        # Increment message counter
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(message_count=Conversation.message_count + 1)
        )
        await self.db.flush()
        return msg

    async def update_state(
        self,
        conversation_id: uuid.UUID,
        collected_data: dict[str, Any] | None = None,
        pending_questions: list[dict] | None = None,
        current_intent: str | None = None,
        title: str | None = None,
    ) -> None:
        values: dict[str, Any] = {}
        if collected_data is not None:
            values["collected_data"] = collected_data
        if pending_questions is not None:
            values["pending_questions"] = pending_questions
        if current_intent is not None:
            values["current_intent"] = current_intent
        if title is not None:
            values["title"] = title
        if values:
            await self.db.execute(update(Conversation).where(Conversation.id == conversation_id).values(**values))
            await self.db.flush()

    async def get_recent_messages(self, conversation_id: uuid.UUID, limit: int = 20) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def archive(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(status=ConversationStatus.archived)
        )
        await self.db.flush()
