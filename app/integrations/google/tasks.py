"""Google Tasks integration service."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.exceptions import IntegrationError, TokenExpiredError
from app.core.logging import get_logger
from google.oauth2.credentials import Credentials

logger = get_logger(__name__)


class GoogleTasksService:
    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials
        self._service = build("tasks", "v1", credentials=credentials, cache_discovery=False)

    def _execute(self, request: Any) -> Any:
        try:
            return request.execute()
        except HttpError as exc:
            if exc.resp.status in (401, 403):
                raise TokenExpiredError("Google Tasks authorization expired", provider="google") from exc
            logger.error("google_tasks_api_error", status=exc.resp.status, reason=exc._get_reason())
            raise IntegrationError(f"Google Tasks API error: {exc._get_reason()}", provider="google") from exc
        except Exception as exc:
            raise IntegrationError(f"Failed to communicate with Google Tasks: {exc}", provider="google") from exc

    async def list_tasks(self, tasklist_id: str = "@default", max_results: int = 100) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        req = self._service.tasks().list(tasklist=tasklist_id, maxResults=max_results)
        result = await loop.run_in_executor(None, self._execute, req)
        return result.get("items", [])

    async def create_task(
        self,
        title: str,
        notes: str | None = None,
        due: datetime | None = None,
        tasklist_id: str = "@default",
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        body: dict[str, Any] = {"title": title}
        if notes:
            body["notes"] = notes
        if due:
            # Google Tasks expects RFC 3339 formatted date
            body["due"] = due.isoformat()

        req = self._service.tasks().insert(tasklist=tasklist_id, body=body)
        return await loop.run_in_executor(None, self._execute, req)

    async def update_task(
        self,
        task_id: str,
        tasklist_id: str = "@default",
        **fields: Any,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        get_req = self._service.tasks().get(tasklist=tasklist_id, task=task_id)
        current = await loop.run_in_executor(None, self._execute, get_req)

        for k, v in fields.items():
            if v is not None:
                current[k] = v

        patch_req = self._service.tasks().patch(tasklist=tasklist_id, task=task_id, body=current)
        return await loop.run_in_executor(None, self._execute, patch_req)

    async def complete_task(self, task_id: str, tasklist_id: str = "@default") -> dict[str, Any]:
        return await self.update_task(
            task_id=task_id,
            tasklist_id=tasklist_id,
            status="completed",
        )
