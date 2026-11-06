"""Gmail integration service."""

from __future__ import annotations

import asyncio
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.exceptions import IntegrationError, TokenExpiredError
from app.core.logging import get_logger
from google.oauth2.credentials import Credentials

logger = get_logger(__name__)


class GmailService:
    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def _execute(self, request: Any) -> Any:
        try:
            return request.execute()
        except HttpError as exc:
            if exc.resp.status in (401, 403):
                raise TokenExpiredError("Gmail authorization expired", provider="google") from exc
            logger.error("gmail_api_error", status=exc.resp.status, reason=exc._get_reason())
            raise IntegrationError(f"Gmail API error: {exc._get_reason()}", provider="google") from exc
        except Exception as exc:
            raise IntegrationError(f"Failed to communicate with Gmail: {exc}", provider="google") from exc

    async def create_draft(
        self,
        to_email: str,
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        message = self._build_mime_message(to_email, subject, body, html_body)
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        req = (
            self._service.users()
            .drafts()
            .create(
                userId="me",
                body={"message": {"raw": raw_message}},
            )
        )
        return await loop.run_in_executor(None, self._execute, req)

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        message = self._build_mime_message(to_email, subject, body, html_body)
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        req = (
            self._service.users()
            .messages()
            .send(
                userId="me",
                body={"raw": raw_message},
            )
        )
        return await loop.run_in_executor(None, self._execute, req)

    def _build_mime_message(
        self,
        to_email: str,
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["Subject"] = subject

        part1 = MIMEText(body, "plain", "utf-8")
        msg.attach(part1)

        if html_body:
            part2 = MIMEText(html_body, "html", "utf-8")
            msg.attach(part2)

        return msg
