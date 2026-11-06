"""Secure executor for registered application tools."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tool_registry import tool_registry
from app.core.datetime_utils import parse_datetime
from app.core.exceptions import ApprovalRequiredError, ToolExecutionError
from app.core.logging import get_logger
from app.db.models import (
    CalendarEvent,
    CalendarEventStatus,
    Contact,
    ScheduledJob,
    Task,
    TaskPriority,
    TaskStatus,
    ToolExecution,
    User,
)

logger = get_logger(__name__)


class ToolExecutor:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user: User,
        plan_id: uuid.UUID | None = None,
        bypass_approval_check: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Validate, authorize, and execute a tool safely."""
        tool_def = tool_registry.get(tool_name)
        if not tool_def:
            raise ToolExecutionError(f"Tool '{tool_name}' is not registered or allowed.")

        # Check approval requirement
        if tool_def.requires_approval and not bypass_approval_check:
            raise ApprovalRequiredError(
                plan_id=str(plan_id or ""),
                message=f"Tool '{tool_name}' modifies data or communicates externally and requires explicit approval.",
            )

        # Check idempotency
        if idempotency_key:
            stmt = select(ToolExecution).where(ToolExecution.idempotency_key == idempotency_key)
            existing = (await self.db.execute(stmt)).scalar_one_or_none()
            if existing:
                return existing.result

        start_time = time.perf_counter()
        success = False
        error_msg: str | None = None
        result: dict[str, Any] = {}

        try:
            result = await self._dispatch(tool_name, arguments, user)
            success = True
        except Exception as exc:
            error_msg = str(exc)
            logger.error("tool_execution_failed", tool=tool_name, error=error_msg)
            raise
        finally:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            execution_record = ToolExecution(
                plan_id=plan_id,
                user_id=user.id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                success=success,
                error_message=error_msg,
                duration_ms=duration_ms,
                idempotency_key=idempotency_key,
            )
            self.db.add(execution_record)
            await self.db.flush()

        return result

    async def _dispatch(self, tool_name: str, args: dict[str, Any], user: User) -> dict[str, Any]:
        if tool_name == "check_calendar_availability":
            return await self._check_availability(args, user)
        elif tool_name == "create_calendar_event":
            return await self._create_calendar_event(args, user)
        elif tool_name == "create_task":
            return await self._create_task(args, user)
        elif tool_name == "list_tasks":
            return await self._list_tasks(args, user)
        elif tool_name == "search_contacts":
            return await self._search_contacts(args, user)
        elif tool_name == "send_email_invitation":
            return await self._send_email_invitation(args, user)
        elif tool_name == "schedule_reminder":
            return await self._schedule_reminder(args, user)
        elif tool_name == "find_free_slots":
            return await self._find_free_slots(args, user)
        else:
            raise ToolExecutionError(f"No execution handler implemented for tool: {tool_name}")

    async def _check_availability(self, args: dict[str, Any], user: User) -> dict[str, Any]:
        start = parse_datetime(args["start_time"])
        end = parse_datetime(args["end_time"])

        # Check local calendar events first
        stmt = select(CalendarEvent).where(
            CalendarEvent.owner_id == user.id,
            CalendarEvent.status == CalendarEventStatus.scheduled,
            CalendarEvent.start_at < end,
            CalendarEvent.end_at > start,
        )
        conflicts = (await self.db.execute(stmt)).scalars().all()
        is_free = len(conflicts) == 0

        # Also check Google Calendar if connected
        google_free = True
        try:
            from app.integrations.google.calendar import GoogleCalendarService
            from app.integrations.google.client import GoogleOAuthClient

            client = GoogleOAuthClient()
            creds = await client.get_credentials(user.id, self.db)
            gcal = GoogleCalendarService(creds)
            google_free = await gcal.check_availability(start, end)
        except Exception:
            # If Google not configured or not connected, rely on local DB
            pass

        return {
            "available": is_free and google_free,
            "local_conflicts_count": len(conflicts),
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        }

    async def _create_calendar_event(self, args: dict[str, Any], user: User) -> dict[str, Any]:
        start = parse_datetime(args["start_time"])
        end = parse_datetime(args["end_time"])
        title = args["title"]
        desc = args.get("description")
        loc = args.get("location")
        attendees = args.get("attendee_emails", [])
        add_meet = args.get("add_google_meet", True)

        google_event_id: str | None = None
        meet_link: str | None = None

        # Try Google Calendar creation if connected
        try:
            from app.integrations.google.calendar import GoogleCalendarService
            from app.integrations.google.client import GoogleOAuthClient

            client = GoogleOAuthClient()
            creds = await client.get_credentials(user.id, self.db)
            gcal = GoogleCalendarService(creds)
            g_event = await gcal.create_event(
                title=title,
                start=start,
                end=end,
                description=desc,
                location=loc,
                attendees_emails=attendees,
                add_meet=add_meet,
            )
            google_event_id = g_event.get("id")
            meet_link = gcal._extract_meet_link(g_event)
        except Exception as e:
            logger.info("google_calendar_skipped_or_failed", reason=str(e))

        # Save to local database
        event = CalendarEvent(
            owner_id=user.id,
            title=title,
            description=desc,
            location=loc,
            start_at=start,
            end_at=end,
            status=CalendarEventStatus.scheduled,
            google_event_id=google_event_id,
            meet_link=meet_link,
        )
        self.db.add(event)
        await self.db.flush()

        return {
            "event_id": str(event.id),
            "title": title,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "google_event_id": google_event_id,
            "meet_link": meet_link,
            "status": "scheduled",
        }

    async def _create_task(self, args: dict[str, Any], user: User) -> dict[str, Any]:
        due_at = parse_datetime(args["due_date"]) if args.get("due_date") else None
        priority_str = args.get("priority", "medium")
        try:
            priority = TaskPriority(priority_str.lower())
        except ValueError:
            priority = TaskPriority.medium

        task = Task(
            owner_id=user.id,
            title=args["title"],
            description=args.get("description"),
            due_at=due_at,
            priority=priority,
            status=TaskStatus.pending,
        )
        self.db.add(task)
        await self.db.flush()

        return {
            "task_id": str(task.id),
            "title": task.title,
            "status": task.status.value,
            "due_at": due_at.isoformat() if due_at else None,
        }

    async def _list_tasks(self, args: dict[str, Any], user: User) -> dict[str, Any]:
        stmt = select(Task).where(Task.owner_id == user.id)
        if args.get("status"):
            try:
                st = TaskStatus(args["status"])
                stmt = stmt.where(Task.status == st)
            except ValueError:
                pass
        limit = args.get("limit", 10)
        stmt = stmt.order_by(Task.created_at.desc()).limit(limit)
        tasks = (await self.db.execute(stmt)).scalars().all()
        return {
            "tasks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "status": t.status.value,
                    "priority": t.priority.value,
                    "due_at": t.due_at.isoformat() if t.due_at else None,
                }
                for t in tasks
            ]
        }

    async def _search_contacts(self, args: dict[str, Any], user: User) -> dict[str, Any]:
        query = f"%{args['query'].lower()}%"
        stmt = select(Contact).where(
            Contact.owner_id == user.id,
            (Contact.full_name.ilike(query)) | (Contact.email.ilike(query)) | (Contact.company.ilike(query)),
        )
        contacts = (await self.db.execute(stmt)).scalars().all()
        return {
            "contacts": [
                {
                    "id": str(c.id),
                    "name": c.full_name,
                    "email": c.email,
                    "company": c.company,
                }
                for c in contacts
            ]
        }

    async def _send_email_invitation(self, args: dict[str, Any], user: User) -> dict[str, Any]:
        to_email = args["to_email"]
        subject = args["subject"]
        body = args["body"]

        try:
            from app.integrations.google.client import GoogleOAuthClient
            from app.integrations.google.gmail import GmailService

            client = GoogleOAuthClient()
            creds = await client.get_credentials(user.id, self.db)
            gmail = GmailService(creds)
            result = await gmail.send_email(to_email=to_email, subject=subject, body=body)
            return {"status": "sent", "to": to_email, "message_id": result.get("id")}
        except Exception as e:
            logger.info("gmail_skipped_or_failed", reason=str(e))
            return {"status": "queued", "to": to_email, "note": "Email recorded; Gmail integration pending."}

    async def _schedule_reminder(self, args: dict[str, Any], user: User) -> dict[str, Any]:
        remind_at = parse_datetime(args["remind_at"])
        title = args["event_title"]
        channel = args.get("channel", "telegram")

        job = ScheduledJob(
            user_id=user.id,
            task_name="send_meeting_reminder",
            scheduled_at=remind_at,
            job_data={"title": title, "channel": channel},
        )
        self.db.add(job)
        await self.db.flush()

        # Enqueue with Celery if available
        try:
            from app.workers.tasks import send_scheduled_reminder_task

            celery_task = send_scheduled_reminder_task.apply_async(args=[str(job.id)], eta=remind_at)
            job.celery_task_id = celery_task.id
            await self.db.flush()
        except Exception:
            pass

        return {
            "job_id": str(job.id),
            "event_title": title,
            "remind_at": remind_at.isoformat(),
            "channel": channel,
        }

    async def _find_free_slots(self, args: dict[str, Any], user: User) -> dict[str, Any]:
        from datetime import UTC, datetime, time, timedelta
        target_date = parse_datetime(args["date"]).date()
        duration_minutes = int(args.get("duration_minutes", 60))

        start_of_day = datetime.combine(target_date, time(9, 0), tzinfo=UTC)
        end_of_day = datetime.combine(target_date, time(18, 0), tzinfo=UTC)

        stmt = select(CalendarEvent).where(
            CalendarEvent.owner_id == user.id,
            CalendarEvent.status == CalendarEventStatus.scheduled,
            CalendarEvent.start_at < end_of_day,
            CalendarEvent.end_at > start_of_day,
        ).order_by(CalendarEvent.start_at.asc())

        busy_events = (await self.db.execute(stmt)).scalars().all()

        free_slots = []
        current = start_of_day
        step = timedelta(minutes=duration_minutes)

        for event in busy_events:
            event_start = event.start_at if event.start_at.tzinfo else event.start_at.replace(tzinfo=UTC)
            event_end = event.end_at if event.end_at.tzinfo else event.end_at.replace(tzinfo=UTC)

            if event_start - current >= step:
                free_slots.append({
                    "start": current.isoformat(),
                    "end": (current + step).isoformat(),
                })
            if event_end > current:
                current = event_end

        if end_of_day - current >= step:
            free_slots.append({
                "start": current.isoformat(),
                "end": (current + step).isoformat(),
            })

        return {
            "date": target_date.isoformat(),
            "duration_minutes": duration_minutes,
            "available_slots": free_slots[:5],
            "total_slots_found": len(free_slots),
        }
