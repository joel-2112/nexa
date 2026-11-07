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

        # Check for explicit cancellation or context reset
        lower_msg = user_message.lower().strip()
        if lower_msg in ["cancel", "reset", "stop", "clear", "nevermind", "never mind", "forget it"]:
            conversation.current_intent = None
            conversation.collected_data = {}
            conversation.pending_questions = []
            await self.db.flush()
            reply = "Understood. I've reset the active request and cleared our conversation context. What would you like to work on?"
            assistant_msg = Message(
                conversation_id=conversation.id,
                role=MessageRole.assistant,
                content=reply,
            )
            self.db.add(assistant_msg)
            conversation.message_count += 1
            await self.db.flush()
            return OrchestratorResponse(response_text=reply)

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
                    tz_str = user.timezone or "Africa/Addis_Ababa"
                    try:
                        from zoneinfo import ZoneInfo
                        dt = dt.astimezone(ZoneInfo(tz_str))
                    except Exception:
                        pass
                    return dt.strftime("%b %d, %Y at %I:%M %p %Z").strip().replace(" 0", " ")
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

            # Clear state so the conversation starts fresh for the next instruction
            conversation.current_intent = None
            conversation.collected_data = {}
            conversation.pending_questions = []
            await self.db.flush()

            return OrchestratorResponse(
                response_text=summary,
                action_plan_id=plan.id,
                clarification_needed=False,
            )

        elif extracted.intent == IntentType.CREATE_TASK:
            plan = await self.planner.create_action_plan(extracted, user, conversation)
            due_iso = extracted.entities.get("due_date") or extracted.entities.get("remind_at")

            def _format_display_dt_local(val: str | None) -> str:
                if not val:
                    return "No due date"
                try:
                    dt = parse_datetime(val)
                    tz_str = user.timezone or "Africa/Addis_Ababa"
                    try:
                        from zoneinfo import ZoneInfo
                        dt = dt.astimezone(ZoneInfo(tz_str))
                    except Exception:
                        pass
                    return dt.strftime("%b %d, %Y at %I:%M %p %Z").strip().replace(" 0", " ")
                except Exception:
                    return str(val)

            due_display = _format_display_dt_local(due_iso)
            task_title = extracted.entities.get("title", "New Task")
            prio = extracted.entities.get("priority", "medium").capitalize()

            steps_text = f"1. Add '{task_title}' to your task list (Priority: {prio})\n"
            if due_iso:
                steps_text += f"2. Schedule Telegram notification for {due_display}"

            summary = (
                f"I've prepared an execution plan for your task:\n\n"
                f"📋 **Action Plan:** {plan.title}\n"
                f"- **Task:** {task_title}\n"
                f"- **Priority:** {prio}\n"
                f"- **Scheduled For:** {due_display}\n\n"
                f"**Planned Steps:**\n"
                f"{steps_text}\n\n"
                f"⚠️ *Please reply **Approve** or tap the button below to confirm.*"
            )

            assistant_msg = Message(
                conversation_id=conversation.id,
                role=MessageRole.assistant,
                content=summary,
                ai_metadata={"action_plan_id": str(plan.id)},
            )
            self.db.add(assistant_msg)
            conversation.message_count += 1

            # Clear state so the conversation starts fresh for the next instruction
            conversation.current_intent = None
            conversation.collected_data = {}
            conversation.pending_questions = []
            await self.db.flush()

            return OrchestratorResponse(
                response_text=summary,
                action_plan_id=plan.id,
                clarification_needed=False,
            )

        # Check if this is a direct calendar availability / conflict check
        if extracted.entities.get("is_conflict_check"):
            start_iso = extracted.entities.get("check_start_iso")
            end_iso = extracted.entities.get("check_end_iso")
            display_range = extracted.entities.get("check_display_range", "that time window")
            if start_iso and end_iso:
                avail_res = await self.executor.execute(
                    tool_name="check_calendar_availability",
                    arguments={"start_time": start_iso, "end_time": end_iso},
                    user=user,
                    bypass_approval_check=True,
                )
                if avail_res.get("available"):
                    reply_text = (
                        f"📅 <b>Calendar Availability:</b>\n\n"
                        f"You are completely <b>free</b> with no conflicts for <b>{display_range}</b>.\n"
                        f"Your schedule is clear!"
                    )
                else:
                    reply_text = (
                        f"⚠️ <b>Scheduling Conflict:</b>\n\n"
                        f"You have a conflicting event scheduled during <b>{display_range}</b>."
                    )
                assistant_msg = Message(
                    conversation_id=conversation.id,
                    role=MessageRole.assistant,
                    content=reply_text,
                )
                self.db.add(assistant_msg)
                conversation.message_count += 1
                await self.db.flush()
                return OrchestratorResponse(
                    response_text=reply_text,
                    executed_tools=[{"tool": "check_calendar_availability", "result": avail_res}],
                )

        # 4. Standard completion for general queries or direct assistance
        messages = await self.context_mgr.build_context_messages(
            conversation=conversation,
            user=user,
            system_prompt=SYSTEM_ORCHESTRATOR_PROMPT,
        )

        tools = tool_registry.get_openai_tools()
        executed_tools: list[dict[str, Any]] = []
        reply_text = ""

        try:
            ai_response = await self.agent.chat_completion(
                messages=messages,
                tools=tools,
            )
            choice = ai_response.choices[0]
            reply_text = choice.message.content or ""

            # Check if LLM requested read-only tool calls
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

        except AIError as ai_err:
            logger.warning("orchestrator_ai_fallback", error=str(ai_err))
            err_str = str(ai_err).lower()
            if "credit" in err_str or "quota" in err_str or "429" in err_str:
                reply_text = (
                    "⚠️ <b>Gemini API Quota Limit</b>\n\n"
                    "Your Gemini API rate limit or quota has been reached. Please check your Google AI Studio dashboard.\n\n"
                    "<i>Note: Core features (scheduling meetings, task management, calendar views, and reminders) continue to operate!</i>"
                )
            else:
                reply_text = (
                    f"I understand your instruction: '{user_message}'. "
                    "NEXA encountered a temporary issue contacting the Gemini model. Please try again."
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
        """Deterministic entity and intent extractor with priority overrides."""
        lower = text.lower().strip()
        entities: dict[str, Any] = {}

        # 1. Explicit Conflict / Availability / Schedule Queries
        is_conflict_or_query = any(
            phrase in lower
            for phrase in [
                "conflict", "conflicts", "am i free", "are there any conflicts",
                "check my schedule", "check my calendar", "what's on my schedule",
                "what is on my schedule", "what do i have", "do i have any",
                "free slots", "free time", "availability", "available",
            ]
        ) and not any(w in lower for w in ["schedule a meeting", "book a meeting", "set up a meeting"])

        # 2. Explicit Task / Reminder Intent
        is_task = any(
            phrase in lower
            for phrase in [
                "remind me to", "remind me", "add task", "create task",
                "task to", "have the task", "have a task", "todo", "to-do",
                "check my email", "check email",
            ]
        ) and not ("meeting with" in lower or ("meeting" in lower and "@" in lower))

        # 3. Explicit New Meeting Booking Request
        is_new_meeting = (
            any(phrase in lower for phrase in ["schedule a meeting", "schedule meeting", "book a meeting", "set up a meeting", "set up a call", "plan a meeting"])
            or ("meeting with" in lower)
            or ("call with" in lower)
        )

        has_pending = bool(conversation.pending_questions)

        if is_conflict_or_query:
            intent = IntentType.GENERAL_QUERY
            conversation.current_intent = None
            conversation.pending_questions = []
            conversation.collected_data = {}

            # Extract time range for direct calendar availability check
            range_match = re.search(
                r"(?:between|from)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:and|to)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
                lower,
            )
            if range_match:
                now = datetime.now(UTC)
                target_date = now
                weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                for idx, day_name in enumerate(weekdays):
                    if day_name in lower:
                        current_weekday = now.weekday()
                        days_ahead = (idx - current_weekday) % 7
                        if days_ahead == 0:
                            days_ahead = 7
                        target_date = now + timedelta(days=days_ahead)
                        break
                if "tomorrow" in lower:
                    target_date = now + timedelta(days=1)

                t1 = range_match.group(1).strip()
                t2 = range_match.group(2).strip()
                if "pm" in t2 and not ("am" in t1 or "pm" in t1):
                    t1 += " pm"
                elif "am" in t2 and not ("am" in t1 or "pm" in t1):
                    t1 += " am"

                try:
                    p1 = parse_datetime(t1)
                    p2 = parse_datetime(t2)
                    start_dt = target_date.replace(hour=p1.hour, minute=p1.minute, second=0, microsecond=0)
                    end_dt = target_date.replace(hour=p2.hour, minute=p2.minute, second=0, microsecond=0)
                    entities["is_conflict_check"] = True
                    entities["check_start_iso"] = start_dt.isoformat()
                    entities["check_end_iso"] = end_dt.isoformat()
                    entities["check_display_range"] = (
                        start_dt.strftime("%A, %b %d from %I:%M %p").replace(" 0", " ")
                        + " to "
                        + end_dt.strftime("%I:%M %p %Z").replace(" 0", " ")
                    )
                except Exception:
                    pass
        elif is_task:
            intent = IntentType.CREATE_TASK
            conversation.current_intent = None
            conversation.pending_questions = []
            conversation.collected_data = {}
        elif is_new_meeting:
            intent = IntentType.SCHEDULE_MEETING
            conversation.collected_data = {}
            conversation.pending_questions = []
        elif has_pending and conversation.current_intent == IntentType.SCHEDULE_MEETING.value:
            intent = IntentType.SCHEDULE_MEETING
        elif any(w in lower for w in ["meeting", "schedule", "meet", "call", "client", "appointment"]):
            intent = IntentType.SCHEDULE_MEETING
        else:
            intent = IntentType.GENERAL_QUERY

        if intent == IntentType.CREATE_TASK:
            now = datetime.now(UTC)
            offset_match = re.search(r"(?:in|after)\s+(\d+)\s*(min(?:ute)?s?|hours?|hrs?|days?)", lower)
            if offset_match:
                val = int(offset_match.group(1))
                unit = offset_match.group(2)
                if "min" in unit:
                    due_dt = now + timedelta(minutes=val)
                elif "hour" in unit or "hr" in unit:
                    due_dt = now + timedelta(hours=val)
                elif "day" in unit:
                    due_dt = now + timedelta(days=val)
                else:
                    due_dt = now + timedelta(minutes=val)
                entities["due_date"] = due_dt.isoformat()
                entities["remind_at"] = due_dt.isoformat()

            # Clean task title
            title = text
            title = re.sub(r"(?:in|after)\s+\d+\s*(?:min(?:ute)?s?|hours?|hrs?|days?)", "", title, flags=re.IGNORECASE)
            for b in [
                r"i\s+will\s+have\s+the\s+task\s+to\b",
                r"i\s+have\s+a\s+task\s+to\b",
                r"task\s+to\b",
                r"remind\s+me\s+to\b",
                r"remind\s+me\b",
                r"add\s+task:?\b",
                r"create\s+task:?\b",
                r"please\b",
            ]:
                title = re.sub(b, "", title, flags=re.IGNORECASE)
            clean_title = title.strip(" :,-.").capitalize()
            entities["title"] = clean_title or text

            if "urgent" in lower or "asap" in lower:
                entities["priority"] = "urgent"
            elif "high" in lower:
                entities["priority"] = "high"
            elif "low" in lower:
                entities["priority"] = "low"
            else:
                entities["priority"] = "medium"

        # Email detection
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
        if email_match:
            entities["client_email"] = email_match.group(0)

        # Check for client name (clean any leading 'client ')
        client_match = re.search(
            r"(?:with|client(?:\s+is)?|name(?:\s+is)?)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)",
            text,
            re.IGNORECASE,
        )
        if client_match:
            raw_name = client_match.group(1).strip()
            clean_name = re.sub(r"^client\s+", "", raw_name, flags=re.IGNORECASE).strip()
            entities["client_name"] = clean_name or raw_name
        elif not entities.get("client_name"):
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

        # Relative offset detection (e.g. "in 20 minutes", "after 1 hour")
        rel_match = re.search(
            r"(?:in|after)\s+(\d+)\s*(min(?:ute)?s?|hours?|hrs?|days?)",
            lower,
        )
        if rel_match:
            entities["relative_offset_val"] = int(rel_match.group(1))
            entities["relative_offset_unit"] = rel_match.group(2)

        # Weekday detection
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for day_name in weekdays:
            if re.search(rf"\b{day_name}\b", lower):
                entities["weekday"] = day_name
                break

        # Relative date/time keywords
        if "tomorrow" in lower:
            entities["date_relative"] = "tomorrow"
        if "today" in lower:
            entities["date_relative"] = "today"

        # Time match (e.g. 12:00 AM, 3:30 PM, 2pm, 14:00)
        time_match = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))", text)
        if time_match:
            entities["time_raw"] = time_match.group(0)

        # Duration match (e.g. 1 hour, 30 minutes)
        # Ensure we don't accidentally capture the relative offset string
        dur_match = re.search(r"(?:for|duration(?:\s+is)?)\s+(\d+)\s*(hour|hr|minute|min)", lower)
        if dur_match:
            entities["duration"] = f"{dur_match.group(1)} {dur_match.group(2)}"
        else:
            text_without_rel = re.sub(r"(?:in|after)\s+\d+\s*(?:min(?:ute)?s?|hours?|hrs?|days?)", "", lower)
            dur_match_fallback = re.search(r"(\d+)\s*(hour|hr|minute|min)", text_without_rel)
            if dur_match_fallback:
                entities["duration"] = f"{dur_match_fallback.group(1)} {dur_match_fallback.group(2)}"
            else:
                entities["duration"] = entities.get("duration", "30 minutes")

        return ExtractedIntent(intent=intent, confidence=0.9, entities=entities)

    def _check_missing_meeting_info(self, data: dict[str, Any]) -> list[str]:
        missing = []
        if not data.get("client_name"):
            missing.append("client_name")
        if not data.get("client_email"):
            missing.append("client_email")
        has_time = bool(
            data.get("start_time")
            or (data.get("date_relative") and data.get("time_raw"))
            or data.get("relative_offset_val")
            or data.get("weekday")
        )
        if not has_time:
            missing.append("meeting_time")
        if not data.get("duration"):
            data["duration"] = "30 minutes"
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
        """Resolve relative times to ISO 8601 timestamps with user timezone awareness."""
        now = datetime.now(UTC)
        try:
            from zoneinfo import ZoneInfo
            user_tz = ZoneInfo(timezone_str or "Africa/Addis_Ababa")
        except Exception:
            user_tz = UTC
        now_local = now.astimezone(user_tz)

        if data.get("relative_offset_val"):
            val = int(data["relative_offset_val"])
            unit = str(data.get("relative_offset_unit", "min")).lower()
            if "hour" in unit or "hr" in unit:
                start_dt = now + timedelta(hours=val)
            elif "day" in unit:
                start_dt = now + timedelta(days=val)
            else:
                start_dt = now + timedelta(minutes=val)
        elif data.get("weekday"):
            day_name = data["weekday"]
            weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            target_idx = weekdays.index(day_name)
            current_weekday = now_local.weekday()
            days_ahead = (target_idx - current_weekday) % 7
            if days_ahead == 0:
                days_ahead = 7
            target_date = (now_local + timedelta(days=days_ahead)).date()
            hour, minute = 10, 0
            if data.get("time_raw"):
                try:
                    parsed_t = parse_datetime(data["time_raw"])
                    hour, minute = parsed_t.hour, parsed_t.minute
                except Exception:
                    pass
            start_local = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=user_tz)
            start_dt = start_local.astimezone(UTC)
        elif data.get("date_relative") == "tomorrow":
            target_date = (now_local + timedelta(days=1)).date()
            hour, minute = 10, 0
            if data.get("time_raw"):
                try:
                    parsed_t = parse_datetime(data["time_raw"])
                    hour, minute = parsed_t.hour, parsed_t.minute
                except Exception:
                    pass
            start_local = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=user_tz)
            start_dt = start_local.astimezone(UTC)
        elif data.get("date_relative") == "today":
            target_date = now_local.date()
            hour, minute = now_local.hour + 1, 0
            if data.get("time_raw"):
                try:
                    parsed_t = parse_datetime(data["time_raw"])
                    hour, minute = parsed_t.hour, parsed_t.minute
                except Exception:
                    pass
            start_local = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=user_tz)
            start_dt = start_local.astimezone(UTC)
        else:
            start_dt = now + timedelta(days=1, hours=2)  # default fallback
            if data.get("time_raw"):
                try:
                    parsed_t = parse_datetime(data["time_raw"])
                    target_date = (now_local + timedelta(days=1)).date()
                    start_local = datetime(target_date.year, target_date.month, target_date.day, parsed_t.hour, parsed_t.minute, tzinfo=user_tz)
                    start_dt = start_local.astimezone(UTC)
                except Exception:
                    pass

        # Parse duration
        duration_minutes = 30
        dur_str = str(data.get("duration", "30 minutes")).lower()
        if "30" in dur_str or "half" in dur_str:
            duration_minutes = 30
        elif "hour" in dur_str or "hr" in dur_str:
            match = re.search(r"(\d+)", dur_str)
            if match:
                duration_minutes = int(match.group(1)) * 60
            else:
                duration_minutes = 60
        elif "minute" in dur_str or "min" in dur_str:
            match = re.search(r"(\d+)", dur_str)
            if match:
                duration_minutes = int(match.group(1))

        end_dt = start_dt + timedelta(minutes=duration_minutes)

        data["start_time"] = start_dt.isoformat()
        data["end_time"] = end_dt.isoformat()
        data["duration_minutes"] = duration_minutes
