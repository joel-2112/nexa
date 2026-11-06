"""Conversation context manager for LLM interactions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, MessageRole, User


class ConversationContextManager:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build_context_messages(
        self,
        conversation: Conversation,
        user: User,
        system_prompt: str,
        max_history_messages: int = 15,
    ) -> list[dict[str, Any]]:
        """Construct the prompt messages array for OpenAI completion."""
        # 1. Format dynamic system prompt with user timezone & current time
        now = datetime.now(UTC)
        formatted_system = system_prompt.format(
            timezone=user.timezone or "Africa/Addis_Ababa",
            current_time=now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            user_name=user.full_name,
        )

        # Append collected conversation memory if any
        if conversation.collected_data:
            memory_summary = json.dumps(conversation.collected_data, default=str)
            formatted_system += f"\n\n[Active State & Collected Data]:\n{memory_summary}"

        if conversation.pending_questions:
            questions_summary = json.dumps(conversation.pending_questions)
            formatted_system += f"\n[Pending Information Inquiries]:\n{questions_summary}"

        messages: list[dict[str, Any]] = [{"role": "system", "content": formatted_system}]

        # 2. Fetch recent conversation messages
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(max_history_messages)
        )
        result = await self.db.execute(stmt)
        history = list(result.scalars().all())
        history.reverse()

        for msg in history:
            role = "user" if msg.role == MessageRole.user else "assistant"
            entry: dict[str, Any] = {"role": role, "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            messages.append(entry)

        return messages

    async def update_collected_data(
        self,
        conversation: Conversation,
        new_data: dict[str, Any],
    ) -> None:
        """Merge newly discovered entities into conversation state."""
        current = dict(conversation.collected_data or {})
        current.update(new_data)
        conversation.collected_data = current
        await self.db.flush()

    async def set_pending_questions(
        self,
        conversation: Conversation,
        questions: list[str],
    ) -> None:
        conversation.pending_questions = [{"question": q, "status": "pending"} for q in questions]
        await self.db.flush()

    async def clear_pending_questions(self, conversation: Conversation) -> None:
        conversation.pending_questions = []
        await self.db.flush()
