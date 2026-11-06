"""Google Calendar integration service."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.exceptions import IntegrationError, TokenExpiredError
from app.core.logging import get_logger
from google.oauth2.credentials import Credentials

logger = get_logger(__name__)


class GoogleCalendarService:
    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def _execute(self, request: Any) -> Any:
        try:
            return request.execute()
        except HttpError as exc:
            if exc.resp.status in (401, 403):
                raise TokenExpiredError("Google Calendar authorization expired", provider="google") from exc
            logger.error("google_calendar_api_error", status=exc.resp.status, reason=exc._get_reason())
            raise IntegrationError(f"Google Calendar API error: {exc._get_reason()}", provider="google") from exc
        except Exception as exc:
            raise IntegrationError(f"Failed to communicate with Google Calendar: {exc}", provider="google") from exc

    async def check_availability(self, start: datetime, end: datetime, calendar_id: str = "primary") -> bool:
        """Check if user has free time between start and end."""
        loop = asyncio.get_running_loop()
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": calendar_id}],
        }
        req = self._service.freebusy().query(body=body)
        result = await loop.run_in_executor(None, self._execute, req)
        busy_slots = result.get("calendars", {}).get(calendar_id, {}).get("busy", [])
        return len(busy_slots) == 0

    async def list_events(
        self,
        time_min: datetime,
        time_max: datetime | None = None,
        max_results: int = 50,
        calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "timeMin": time_min.isoformat(),
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_max:
            kwargs["timeMax"] = time_max.isoformat()

        req = self._service.events().list(**kwargs)
        result = await loop.run_in_executor(None, self._execute, req)
        return result.get("items", [])

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
        location: str | None = None,
        attendees_emails: list[str] | None = None,
        add_meet: bool = True,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Create a Google Calendar event.

        Handles Google Meet conference creation and verifies conference URL availability.
        """
        loop = asyncio.get_running_loop()
        event_body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendees_emails:
            event_body["attendees"] = [{"email": email} for email in attendees_emails]

        conference_data_version = 0
        if add_meet:
            conference_data_version = 1
            request_id = str(uuid.uuid4())
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": request_id,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        req = self._service.events().insert(
            calendarId=calendar_id,
            body=event_body,
            conferenceDataVersion=conference_data_version,
            sendUpdates="all" if attendees_emails else "none",
        )
        created_event = await loop.run_in_executor(None, self._execute, req)

        # Google Meet creation can be asynchronous: verify or poll if link not present immediately
        if add_meet:
            meet_url = self._extract_meet_link(created_event)
            event_id = created_event.get("id")
            retries = 3
            while not meet_url and retries > 0 and event_id:
                await asyncio.sleep(1.0)
                get_req = self._service.events().get(calendarId=calendar_id, eventId=event_id)
                created_event = await loop.run_in_executor(None, self._execute, get_req)
                meet_url = self._extract_meet_link(created_event)
                retries -= 1

        return created_event

    def _extract_meet_link(self, event_data: dict[str, Any]) -> str | None:
        # Check conferenceData
        conf_data = event_data.get("conferenceData", {})
        for ep in conf_data.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                return ep.get("uri")
        # Fallback to hangoutLink
        return event_data.get("hangoutLink")

    async def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        **fields: Any,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        get_req = self._service.events().get(calendarId=calendar_id, eventId=event_id)
        current = await loop.run_in_executor(None, self._execute, get_req)

        for k, v in fields.items():
            if v is not None:
                current[k] = v

        patch_req = self._service.events().patch(calendarId=calendar_id, eventId=event_id, body=current)
        return await loop.run_in_executor(None, self._execute, patch_req)

    async def cancel_event(self, event_id: str, calendar_id: str = "primary") -> None:
        loop = asyncio.get_running_loop()
        del_req = self._service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="all")
        await loop.run_in_executor(None, self._execute, del_req)
