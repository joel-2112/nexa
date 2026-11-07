"""AI conversation service — orchestrates OpenAI calls and tool execution."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from openai import AsyncOpenAI, OpenAIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import AIError
from app.core.logging import get_logger
from app.db.models import (
    ActionPlan,
    ActionPlanStatus,
    ActionStep,
    ActionStepStatus,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)
from app.modules.ai.schemas import (
    ActionPlanResponse,
    ChatResponse,
    MessageResponse,
)
from app.modules.ai.tool_executor import ToolExecutor
from app.modules.ai.tools import APPROVAL_REQUIRED_TOOLS, TOOLS

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are NEXA, a highly capable AI personal executive assistant.
You help users manage their calendar, tasks, contacts, emails, and daily workflow.

Key behaviors:
- Always be concise and professional
- When creating events or tasks, confirm details with the user before proceeding
- Use tools to take actions; never fabricate data
- If you need clarification, ask one clear question at a time
- For actions that modify data or send messages, create an action plan for user approval
- Format dates and times in a human-readable way
- The user's timezone is {timezone}
- Current datetime: {current_datetime}
"""


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(self, user_id: uuid.UUID, conversation_id: uuid.UUID | None) -> Conversation:
        if conversation_id is not None:
            result = await self.db.execute(
                select(Conversation)
                .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
                .options(selectinload(Conversation.messages))
            )
            conv = result.scalar_one_or_none()
            if conv is not None:
                return conv

        # Create new conversation
        conv = Conversation(user_id=user_id, status=ConversationStatus.active)
        self.db.add(conv)
        await self.db.flush()
        return conv

    async def get_with_messages(self, conv_id: uuid.UUID, user_id: uuid.UUID) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conv_id, Conversation.user_id == user_id)
            .options(selectinload(Conversation.messages))
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID, page: int = 1, page_size: int = 20) -> list[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all())

    async def add_message(
        self,
        conversation: Conversation,
        role: MessageRole,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tokens_used: int | None = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            tool_calls=tool_calls or [],
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tokens_used=tokens_used,
        )
        self.db.add(msg)
        conversation.message_count = (conversation.message_count or 0) + 1
        await self.db.flush()
        return msg


class ActionPlanRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        title: str,
        intent: str,
        steps: list[dict[str, Any]],
    ) -> ActionPlan:
        plan = ActionPlan(
            user_id=user_id,
            conversation_id=conversation_id,
            title=title,
            intent=intent,
            status=ActionPlanStatus.pending_approval,
        )
        self.db.add(plan)
        await self.db.flush()

        for i, step_data in enumerate(steps):
            step = ActionStep(
                plan_id=plan.id,
                step_order=i,
                tool_name=step_data["tool_name"],
                description=step_data["description"],
                arguments=step_data.get("arguments", {}),
                requires_approval=step_data.get("requires_approval", True),
            )
            self.db.add(step)
        await self.db.flush()
        return plan

    async def get_by_id(self, plan_id: uuid.UUID, user_id: uuid.UUID) -> ActionPlan | None:
        result = await self.db.execute(
            select(ActionPlan)
            .where(ActionPlan.id == plan_id, ActionPlan.user_id == user_id)
            .options(selectinload(ActionPlan.steps))
        )
        return result.scalar_one_or_none()

    async def approve(self, plan: ActionPlan) -> ActionPlan:
        plan.status = ActionPlanStatus.approved
        plan.approved_at = datetime.now(UTC)
        await self.db.flush()
        return plan

    async def reject(self, plan: ActionPlan, reason: str | None) -> ActionPlan:
        plan.status = ActionPlanStatus.rejected
        plan.rejected_at = datetime.now(UTC)
        plan.rejection_reason = reason
        await self.db.flush()
        return plan

    async def mark_executing(self, plan: ActionPlan) -> None:
        plan.status = ActionPlanStatus.executing
        await self.db.flush()

    async def mark_completed(self, plan: ActionPlan, result_data: dict[str, Any]) -> None:
        plan.status = ActionPlanStatus.completed
        plan.completed_at = datetime.now(UTC)
        plan.result_data = result_data
        await self.db.flush()

    async def mark_failed(self, plan: ActionPlan, error: str) -> None:
        plan.status = ActionPlanStatus.failed
        plan.result_data = {"error": error}
        await self.db.flush()


class AIService:
    """Orchestrates AI conversations with tool use and action plan management."""

    def __init__(self, db: AsyncSession, user_id: uuid.UUID, user_timezone: str) -> None:
        self.db = db
        self.user_id = user_id
        self.user_timezone = user_timezone
        client_kwargs: dict[str, Any] = {
            "api_key": settings.GEMINI_API_KEY or settings.OPENAI_API_KEY,
            "timeout": settings.OPENAI_TIMEOUT,
        }
        if settings.is_gemini_active:
            client_kwargs["base_url"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
        self.client = AsyncOpenAI(**client_kwargs)
        self.conv_repo = ConversationRepository(db)
        self.plan_repo = ActionPlanRepository(db)
        self.tool_executor = ToolExecutor(db, user_id)

    async def chat(
        self,
        user_message: str,
        conversation_id: uuid.UUID | None = None,
    ) -> ChatResponse:
        """Process a user message and return the AI response."""
        conv = await self.conv_repo.get_or_create(self.user_id, conversation_id)

        # Save user message
        await self.conv_repo.add_message(conv, MessageRole.user, user_message)

        # Build message history for OpenAI
        messages = self._build_messages(conv, user_message)

        # Call OpenAI
        try:
            response = await self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=settings.OPENAI_TEMPERATURE,
                max_tokens=settings.OPENAI_MAX_TOKENS,
            )
        except OpenAIError as exc:
            logger.error("openai_error", error=str(exc))
            raise AIError(f"AI service error: {exc}") from exc

        choice = response.choices[0]
        assistant_msg = choice.message
        tokens_used = response.usage.total_tokens if response.usage else None

        # Check for tool calls requiring approval
        action_plan_resp = None
        if assistant_msg.tool_calls:
            needs_approval = any(tc.function.name in APPROVAL_REQUIRED_TOOLS for tc in assistant_msg.tool_calls)

            if needs_approval:
                # Create action plan pending user approval
                steps = []
                for tc in assistant_msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    steps.append(
                        {
                            "tool_name": tc.function.name,
                            "description": self._describe_tool_call(tc.function.name, args),
                            "arguments": args,
                            "requires_approval": tc.function.name in APPROVAL_REQUIRED_TOOLS,
                        }
                    )

                plan = await self.plan_repo.create(
                    user_id=self.user_id,
                    conversation_id=conv.id,
                    title=f"Action plan for: {user_message[:80]}",
                    intent=steps[0]["tool_name"] if steps else "unknown",
                    steps=steps,
                )
                action_plan_resp = ActionPlanResponse.model_validate(plan)

                content = (
                    "I've prepared an action plan for your request. "
                    "Please review and approve the steps above before I proceed."
                )
            else:
                # Execute read-only tools immediately
                content, tool_results = await self._execute_tools(assistant_msg.tool_calls)
        else:
            content = assistant_msg.content or ""

        # Save assistant message
        saved_msg = await self.conv_repo.add_message(
            conv,
            MessageRole.assistant,
            content,
            tokens_used=tokens_used,
        )

        return ChatResponse(
            conversation_id=conv.id,
            message=MessageResponse.model_validate(saved_msg),
            action_plan=action_plan_resp,
        )

    async def execute_plan(self, plan_id: uuid.UUID) -> ActionPlanResponse:
        """Execute an approved action plan step by step."""
        plan = await self.plan_repo.get_by_id(plan_id, self.user_id)
        if plan is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError("Action plan not found")
        if plan.status != ActionPlanStatus.approved:
            from app.core.exceptions import ValidationError

            raise ValidationError("Plan must be approved before execution")

        await self.plan_repo.mark_executing(plan)
        results: dict[str, Any] = {}

        try:
            for step in sorted(plan.steps, key=lambda s: s.step_order):
                step.status = ActionStepStatus.running
                step.started_at = datetime.now(UTC)
                await self.db.flush()

                result = await self.tool_executor.execute(step.tool_name, step.arguments)

                step.result = result
                step.completed_at = datetime.now(UTC)
                if "error" in result:
                    step.status = ActionStepStatus.failed
                    step.error_message = result["error"]
                else:
                    step.status = ActionStepStatus.completed
                results[str(step.id)] = result
                await self.db.flush()

            await self.plan_repo.mark_completed(plan, results)
        except Exception as exc:
            await self.plan_repo.mark_failed(plan, str(exc))
            raise

        return ActionPlanResponse.model_validate(plan)

    def _build_messages(self, conv: Conversation, new_message: str) -> list[dict[str, Any]]:
        system = SYSTEM_PROMPT.format(
            timezone=self.user_timezone,
            current_datetime=datetime.now(UTC).isoformat(),
        )
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]

        # Include recent history (last 20 messages)
        history = getattr(conv, "messages", [])
        for m in history[-20:]:
            if m.role in (MessageRole.user, MessageRole.assistant):
                msgs.append({"role": m.role.value, "content": m.content})

        return msgs

    async def _execute_tools(self, tool_calls: list[Any]) -> tuple[str, dict[str, Any]]:
        results: dict[str, Any] = {}
        summary_parts: list[str] = []

        for tc in tool_calls:
            args = json.loads(tc.function.arguments)
            result = await self.tool_executor.execute(tc.function.name, args)
            results[tc.id] = result
            if "error" not in result:
                summary_parts.append(f"✓ {tc.function.name}: completed")
            else:
                summary_parts.append(f"✗ {tc.function.name}: {result['error']}")

        content = "\n".join(summary_parts) if summary_parts else "Done."
        return content, results

    @staticmethod
    def _describe_tool_call(tool_name: str, args: dict[str, Any]) -> str:
        descriptions = {
            "create_calendar_event": (f"Create calendar event '{args.get('title', '')}' on {args.get('start_at', '')}"),
            "send_email": (f"Send email to {args.get('to', '')} with subject '{args.get('subject', '')}'"),
            "send_telegram_message": (f"Send Telegram message: {str(args.get('message', ''))[:50]}"),
            "create_task": f"Create task '{args.get('title', '')}'",
            "update_task_status": (f"Update task {args.get('task_id', '')} to {args.get('status', '')}"),
        }
        return descriptions.get(tool_name, f"Execute {tool_name}")
