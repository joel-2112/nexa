"""Tool executor — dispatches AI tool calls to the appropriate services."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.calendar.schemas import CalendarEventCreate, ParticipantCreate
from app.modules.calendar.service import CalendarService
from app.modules.contacts.repository import ContactRepository
from app.modules.tasks.schemas import TaskCreate
from app.modules.tasks.service import TaskService

logger = get_logger(__name__)


class ToolExecutor:
    """Executes tool calls dispatched by the AI and returns structured results."""

    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self.db = db
        self.user_id = user_id

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call and return a JSON-serialisable result dict."""
        handler = getattr(self, f"_tool_{tool_name}", None)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            result = await handler(**arguments)
            return result
        except Exception as exc:
            logger.error("tool_execution_error", tool=tool_name, error=str(exc))
            return {"error": str(exc), "tool": tool_name}

    # ------------------------------------------------------------------
    # Calendar tools
    # ------------------------------------------------------------------

    async def _tool_create_calendar_event(
        self,
        title: str,
        start_at: str,
        end_at: str,
        description: str | None = None,
        location: str | None = None,
        participants: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = CalendarEventCreate(
            title=title,
            description=description,
            location=location,
            start_at=datetime.fromisoformat(start_at),
            end_at=datetime.fromisoformat(end_at),
            participants=[
                ParticipantCreate(email=p["email"], full_name=p.get("full_name")) for p in (participants or [])
            ],
        )
        svc = CalendarService(self.db)
        event = await svc.create_event(self.user_id, payload)
        return {
            "event_id": str(event.id),
            "title": event.title,
            "start_at": event.start_at.isoformat(),
            "end_at": event.end_at.isoformat(),
            "status": "created",
        }

    async def _tool_get_calendar_events(
        self,
        start_from: str | None = None,
        start_to: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        svc = CalendarService(self.db)
        result = await svc.list_events(
            owner_id=self.user_id,
            start_from=datetime.fromisoformat(start_from) if start_from else None,
            start_to=datetime.fromisoformat(start_to) if start_to else None,
            page=1,
            page_size=min(limit, 50),
        )
        return {
            "events": [
                {
                    "id": str(e.id),
                    "title": e.title,
                    "start_at": e.start_at.isoformat(),
                    "end_at": e.end_at.isoformat(),
                    "location": e.location,
                    "status": e.status,
                }
                for e in result.items
            ],
            "total": result.total,
        }

    # ------------------------------------------------------------------
    # Task tools
    # ------------------------------------------------------------------

    async def _tool_create_task(
        self,
        title: str,
        description: str | None = None,
        priority: str = "medium",
        due_at: str | None = None,
    ) -> dict[str, Any]:
        from app.db.models import TaskPriority

        payload = TaskCreate(
            title=title,
            description=description,
            priority=TaskPriority(priority),
            due_at=datetime.fromisoformat(due_at) if due_at else None,
        )
        svc = TaskService(self.db)
        task = await svc.create_task(self.user_id, payload)
        return {
            "task_id": str(task.id),
            "title": task.title,
            "priority": task.priority,
            "status": "created",
        }

    async def _tool_get_tasks(
        self,
        status: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        from app.db.models import TaskStatus

        svc = TaskService(self.db)
        result = await svc.list_tasks(
            owner_id=self.user_id,
            status=TaskStatus(status) if status else None,
            page=1,
            page_size=min(limit, 50),
        )
        return {
            "tasks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "status": t.status,
                    "priority": t.priority,
                    "due_at": t.due_at.isoformat() if t.due_at else None,
                }
                for t in result.items
            ],
            "total": result.total,
        }

    async def _tool_update_task_status(
        self,
        task_id: str,
        status: str,
    ) -> dict[str, Any]:
        from app.db.models import TaskStatus
        from app.modules.tasks.schemas import TaskUpdate

        svc = TaskService(self.db)
        task = await svc.update_task(
            task_id=uuid.UUID(task_id),
            owner_id=self.user_id,
            payload=TaskUpdate(status=TaskStatus(status)),
        )
        return {"task_id": str(task.id), "status": task.status, "updated": True}

    # ------------------------------------------------------------------
    # Contact tools
    # ------------------------------------------------------------------

    async def _tool_search_contacts(
        self,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        repo = ContactRepository(self.db)
        contacts, total = await repo.list_for_user(
            owner_id=self.user_id,
            search=query,
            page=1,
            page_size=min(limit, 20),
        )
        return {
            "contacts": [
                {
                    "id": str(c.id),
                    "full_name": c.full_name,
                    "email": c.email,
                    "phone": c.phone,
                    "company": c.company,
                }
                for c in contacts
            ],
            "total": total,
        }

    # ------------------------------------------------------------------
    # Notification tools (Telegram / email stubs – real impl in integrations)
    # ------------------------------------------------------------------

    async def _tool_send_telegram_message(self, message: str) -> dict[str, Any]:
        """Send a Telegram message to the user via the notification service."""
        from app.modules.auth.repository import UserRepository
        from app.modules.notifications.service import NotificationService

        user_repo = UserRepository(self.db)
        user = await user_repo.get_by_id(self.user_id)
        if user is None or user.telegram_id is None:
            return {"error": "User has no linked Telegram account", "sent": False}

        svc = NotificationService(self.db)
        await svc.send_telegram(
            user_id=self.user_id,
            telegram_id=user.telegram_id,
            text=message,
        )
        return {"sent": True, "channel": "telegram"}

    async def _tool_send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send an email via Gmail (requires connected Google account)."""
        from app.modules.integrations.google_service import GoogleService

        svc = GoogleService(self.db, self.user_id)
        result = await svc.send_email(to=to, subject=subject, body=body, cc=cc or [])
        return {"sent": result, "to": to, "subject": subject}
