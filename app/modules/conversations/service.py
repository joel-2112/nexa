"""Conversations service with orchestrator integration."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import NexaOrchestrator
from app.ai.schemas import OrchestratorResponse
from app.core.exceptions import NotFoundError
from app.db.models import Conversation, Message, User
from app.modules.conversations.repository import ConversationRepository


class ConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ConversationRepository(db)
        self.orchestrator = NexaOrchestrator(db)

    async def create(self, user_id: uuid.UUID, title: str | None = None) -> Conversation:
        return await self.repo.create(user_id, title)

    async def get(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation:
        conv = await self.repo.get_by_id_with_messages(conversation_id, user_id)
        if conv is None:
            raise NotFoundError("Conversation not found")
        return conv

    async def list(self, user_id: uuid.UUID, page: int = 1, size: int = 20) -> tuple[list[Conversation], int]:
        return await self.repo.list_by_user(user_id, page, size)

    async def add_user_message_and_respond(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID, content: str
    ) -> tuple[Message, OrchestratorResponse]:
        # 1. Verify conversation ownership
        conv = await self.repo.get_by_id(conversation_id, user_id)
        if conv is None:
            raise NotFoundError("Conversation not found")

        # 2. Fetch User object
        user_stmt = select(User).where(User.id == user_id)
        user = (await self.db.execute(user_stmt)).scalar_one_or_none()
        if not user:
            raise NotFoundError("User not found")

        # 3. Process via AI Orchestrator
        orch_res = await self.orchestrator.process_message(
            user=user,
            conversation=conv,
            user_message=content,
        )

        # 4. Fetch the newly created assistant message
        recent_messages = await self.repo.get_recent_messages(conversation_id, limit=1)
        latest_msg = recent_messages[-1] if recent_messages else None

        return latest_msg, orch_res

    async def archive(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
        conv = await self.repo.get_by_id(conversation_id, user_id)
        if conv is None:
            raise NotFoundError("Conversation not found")
        await self.repo.archive(conversation_id, user_id)
