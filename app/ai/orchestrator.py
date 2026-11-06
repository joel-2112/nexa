"""High-level Orchestrator coordinating context, LLM, planning, and execution."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent import NexaAgent
from app.ai.context import ConversationContextManager
from app.ai.planner import NexaPlanner
from app.ai.prompts.system import SYSTEM_ORCHESTRATOR_PROMPT
from app.ai.schemas import ExtractedIntent, IntentType, OrchestratorResponse
from app.ai.tool_executor import ToolExecutor
from app.ai.tool_registry import tool_registry
from app.core.datetime_utils import parse_datetime
from app.core.exceptions import AIError
from app.core.logging import get_logger
from app.db.models import Conversation, Message, MessageRole, User

logger = get_logger(__name__)


class NexaOrchestrator:
    def __init__(self, db: AsyncSession, agent: NexaAgent | None = None) -> None:
        self.db = db
        self.agent = agent or NexaAgent()
        self.context_mgr = ConversationContextManager(db)
        self.planner = NexaPlanner(db, self.agent)
        self.executor = ToolExecutor(db)

    async def process_message(
        self,
        user: User,
        conversation: Conversation,
        user_message: str,
    ) -> OrchestratorResponse:
        """Process incoming user message through understanding, planning, or follow-up."""
        # 1. Save user message to database
        user_msg_record = Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=user_message,
        )
        self.db.add(user_msg_record)
        conversation.message_count += 1
        await self.db.flush()

        # 2. Extract or update collected state from message
        extracted = await self._analyze_intent_and_entities(user, conversation, user_message)

        # Merge extracted entities into conversation memory
        if extracted.entities:
            await self.context_mgr.update_collected_data(conversation, extracted.entities)

        conversation.current_intent = extracted.intent.value
        await self.db.flush()

        # 3. Check for missing information required for the intent
        all_collected = dict(conversation.collected_data or {})

        if extracted.intent == IntentType.SCHEDULE_MEETING:
            missing = self._check_missing_meeting_info(all_collected)
            if missing:
                follow_up = self._build_meeting_follow_up_question(missing, all_collected)
                await self.context_mgr.set_pending_questions(conversation, missing)

                # Save assistant response
                assistant_msg = Message(
                    conversation_id=conversation.id,
                    role=MessageRole.assistant,
                    content=follow_up,
                )
                self.db.add(assistant_msg)
                conversation.message_count += 1
                await self.db.flush()

                return OrchestratorResponse(
                    response_text=follow_up,
                    clarification_needed=True,
                    follow_up_questions=missing,
                )

            # All required information is collected! Generate Action Plan
            await self.context_mgr.clear_pending_questions(conversation)

            # Format times properly
            self._normalize_meeting_times(all_collected, user.timezone or "Africa/Addis_Ababa")
            extracted.entities = all_collected

            plan = await self.planner.create_action_plan(extracted, user, conversation)

            def _format_display_dt(val: str | None) -> str:
                if not val:
                    return "Not set"
                try:
                    dt = parse_datetime(val)
                    return dt.strftime("%b %d, %Y at %I:%M %p %Z").strip()
                except Exception:
                    return str(val)

            start_display = _format_display_dt(all_collected.get("start_time"))
            end_display = _format_display_dt(all_collected.get("end_time"))

            summary = (
                f"I've prepared an execution plan for your meeting:\n\n"
                f"📋 **Action Plan:** {plan.title}\n"
                f"- **Start Time:** {start_display}\n"
                f"- **End Time:** {end_display}\n"
                f"- **Client:** {all_collected.get('client_name')} ({all_collected.get('client_email')})\n"
                f"- **Topic:** {all_collected.get('topic')}\n\n"
                f"**Planned Steps:**\n"
                f"1. Check calendar availability\n"
                f"2. Create Google Calendar event with Meet link\n"
                f"3. Send invitation email to client\n"
                f"4. Create preparation task\n"
                f"5. Schedule reminder 10 minutes prior\n\n"
                f"⚠️ *This plan requires your approval before sending invitations or modifying your calendar.* "
                f"Please reply **Approve** or click approve in the dashboard."
            )

            assistant_msg = Message(
                conversation_id=conversation.id,
                role=MessageRole.assistant,
                content=summary,
                ai_metadata={"action_plan_id": str(plan.id)},
            )
            self.db.add(assistant_msg)
            conversation.message_count += 1
            await self.db.flush()

            return OrchestratorResponse(
                response_text=summary,
                action_plan_id=plan.id,
                clarification_needed=False,
            )

        # 4. Standard completion for general queries or direct assistance
        messages = await self.context_mgr.build_context_messages(
            conversation=conversation,
            user=user,
            system_prompt=SYSTEM_ORCHESTRATOR_PROMPT,
        )

        tools = tool_registry.get_openai_tools()

        try:
            ai_response = await self.agent.chat_completion(
                messages=messages,
                tools=tools,
            )
            choice = ai_response.choices[0]
            reply_text = choice.message.content or ""

            # Check if LLM requested read-only tool calls
            executed_tools = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    fn_name = tc.function.name
                    fn_args = json.loads(tc.function.arguments)
                    # If tool does not require approval, execute immediately
                    if not tool_registry.is_approval_required(fn_name):
                        tool_res = await self.executor.execute(
                            tool_name=fn_name,
                            arguments=fn_args,
                            user=user,
                            bypass_approval_check=True,
                        )
                        executed_tools.append({"tool": fn_name, "result": tool_res})

                if not reply_text and executed_tools:
                    reply_text = f"I've checked the details: {json.dumps(executed_tools, default=str)}"

            if not reply_text:
                reply_text = "I have processed your request. How else may I assist you?"

        except AIError:
            # Fallback when OpenAI key is absent or in demo mode
            reply_text = (
                f"I understand your instruction: '{user_message}'. "
                "To enable live AI completions, please configure OPENAI_API_KEY."
            )

        assistant_msg = Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=reply_text,
        )
        self.db.add(assistant_msg)
        conversation.message_count += 1
        await self.db.flush()

        return OrchestratorResponse(response_text=reply_text, executed_tools=executed_tools)

    async def _analyze_intent_and_entities(self, user: User, conversation: Conversation, text: str) -> ExtractedIntent:
        """Deterministic entity and intent extractor with LLM or pattern fallbacks."""
        lower = text.lower()
        entities: dict[str, Any] = {}

        # Preserve active conversation intent if in follow-up mode
        if conversation.current_intent == IntentType.SCHEDULE_MEETING.value:
            intent = IntentType.SCHEDULE_MEETING
        elif any(w in lower for w in ["meeting", "schedule", "meet", "call", "client", "appointment"]):
            intent = IntentType.SCHEDULE_MEETING
        elif any(w in lower for w in ["task", "todo", "remind me to", "prepare"]):
            intent = IntentType.CREATE_TASK
            entities["title"] = text
        else:
            intent = IntentType.GENERAL_QUERY

        # Email detection
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
        if email_match:
            entities["client_email"] = email_match.group(0)

        # Check for client name
        client_match = re.search(
            r"(?:with|client(?:\s+is)?|name(?:\s+is)?)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)",
            text,
            re.IGNORECASE,
        )
        if client_match:
            entities["client_name"] = client_match.group(1)
        elif not entities.get("client_name"):
            # Check if pending question was client_name and message contains a 2-word capitalized name
            name_match = re.search(r"\b([A-Z][a-zA-Z]+\s+[A-Z][a-zA-Z]+)\b", text)
            if name_match:
                entities["client_name"] = name_match.group(1)

        # Check for topic
        topic_match = re.search(
            r"(?:about|regarding|discuss(?:ing)?)\s+(.+?)(?:\.|$|,|with|at)",
            text,
            re.IGNORECASE,
        )
        if topic_match:
            entities["topic"] = topic_match.group(1).strip()

        # Relative date/time keywords
        if "tomorrow" in lower:
            entities["date_relative"] = "tomorrow"
        if "today" in lower:
            entities["date_relative"] = "today"

        # Time match (e.g. 12:00 AM, 3:30 PM, 2pm, 14:00)
        time_match = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)", text)
        if time_match:
            entities["time_raw"] = time_match.group(0)

        # Duration match (e.g. 1 hour, 30 minutes)
        dur_match = re.search(r"(\d+)\s*(hour|hr|minute|min)", lower)
        if dur_match:
            entities["duration"] = f"{dur_match.group(1)} {dur_match.group(2)}"

        return ExtractedIntent(intent=intent, confidence=0.9, entities=entities)

    def _check_missing_meeting_info(self, data: dict[str, Any]) -> list[str]:
        missing = []
        if not data.get("client_name"):
            missing.append("client_name")
        if not data.get("client_email"):
            missing.append("client_email")
        if not data.get("start_time") and not (data.get("date_relative") and data.get("time_raw")):
            missing.append("meeting_time")
        if not data.get("duration"):
            missing.append("duration")
        return missing

    def _build_meeting_follow_up_question(self, missing: list[str], data: dict[str, Any]) -> str:
        if "client_name" in missing:
            return "Who is the client you'll be meeting with?"
        if "client_email" in missing:
            name = data.get("client_name", "the client")
            return f"What is {name}'s email address so I can invite them?"
        if "duration" in missing:
            return "How long should the meeting take (e.g., 30 minutes, 1 hour)?"
        if "meeting_time" in missing:
            return "What date and time should the meeting be scheduled for?"
        return "Could you provide more details about this meeting?"

    def _normalize_meeting_times(self, data: dict[str, Any], timezone_str: str) -> None:
        """Resolve relative times to ISO 8601 timestamps."""
        now = datetime.now(UTC)
        start_dt = now + timedelta(days=1, hours=2)  # default fallback

        if data.get("date_relative") == "tomorrow":
            start_dt = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

        # Parse time if raw string exists
        if data.get("time_raw"):
            try:
                # E.g. 12:00 PM or 2:00 PM
                t_str = data["time_raw"]
                parsed_t = parse_datetime(t_str)
                start_dt = start_dt.replace(hour=parsed_t.hour, minute=parsed_t.minute)
            except Exception:
                pass

        # Parse duration
        duration_minutes = 60
        dur_str = str(data.get("duration", "1 hour")).lower()
        if "30" in dur_str or "half" in dur_str:
            duration_minutes = 30
        elif "hour" in dur_str:
            match = re.search(r"(\d+)", dur_str)
            if match:
                duration_minutes = int(match.group(1)) * 60

        end_dt = start_dt + timedelta(minutes=duration_minutes)

        data["start_time"] = start_dt.isoformat()
        data["end_time"] = end_dt.isoformat()
        data["duration_minutes"] = duration_minutes
