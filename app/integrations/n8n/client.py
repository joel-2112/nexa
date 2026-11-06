"""n8n automation integration client."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import IntegrationError, IntegrationNotConfiguredError
from app.core.logging import get_logger

logger = get_logger(__name__)


class N8nClient:
    def __init__(self) -> None:
        self.base_url = settings.N8N_BASE_URL.rstrip("/")
        self.api_key = settings.N8N_API_KEY
        self.webhook_secret = settings.N8N_WEBHOOK_SECRET

    def _ensure_configured(self) -> None:
        if not settings.n8n_configured:
            raise IntegrationNotConfiguredError(
                "n8n is not configured (N8N_API_KEY or N8N_BASE_URL missing).",
                provider="n8n",
            )

    def generate_signature(self, payload: bytes) -> str:
        if not self.webhook_secret:
            return ""
        return hmac.new(self.webhook_secret.encode(), payload, hashlib.sha256).hexdigest()

    def verify_callback_signature(self, payload: bytes, signature: str) -> bool:
        if not self.webhook_secret:
            return True
        expected = self.generate_signature(payload)
        return hmac.compare_digest(expected, signature)

    async def trigger_workflow_webhook(
        self,
        path: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Trigger an n8n webhook workflow using authenticated POST."""
        self._ensure_configured()
        url = f"{self.base_url}/webhook/{path.lstrip('/')}"

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-N8N-API-KEY": self.api_key,
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.error("n8n_webhook_failed", status=resp.status_code, body=resp.text)
                    raise IntegrationError(f"n8n webhook error {resp.status_code}: {resp.text}", provider="n8n")
                return resp.json() if resp.text else {"status": "accepted"}
            except httpx.RequestError as exc:
                raise IntegrationError(f"Failed to communicate with n8n: {exc}", provider="n8n") from exc

    async def trigger_calendar_event_workflow(
        self, event_data: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        workflow_id = settings.N8N_WORKFLOW_CALENDAR_EVENT or "calendar-event-created"
        return await self.trigger_workflow_webhook(
            path=workflow_id,
            payload={"type": "calendar_event_created", "data": event_data},
            idempotency_key=idempotency_key,
        )

    async def trigger_send_email_workflow(
        self, email_data: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        workflow_id = settings.N8N_WORKFLOW_SEND_EMAIL or "send-email"
        return await self.trigger_workflow_webhook(
            path=workflow_id,
            payload={"type": "send_email", "data": email_data},
            idempotency_key=idempotency_key,
        )

    async def trigger_send_reminder_workflow(
        self, reminder_data: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        workflow_id = settings.N8N_WORKFLOW_SEND_REMINDER or "send-reminder"
        return await self.trigger_workflow_webhook(
            path=workflow_id,
            payload={"type": "send_reminder", "data": reminder_data},
            idempotency_key=idempotency_key,
        )
