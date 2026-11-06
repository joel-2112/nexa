"""Tests for external integrations, interactive telegram callbacks, and graceful degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from httpx import AsyncClient

from app.ai.planner import NexaPlanner
from app.ai.schemas import ExtractedIntent, IntentType
from app.core.config import settings
from app.core.exceptions import IntegrationNotConfiguredError
from app.db.models import ActionPlanStatus
from app.integrations.n8n.client import N8nClient
from app.integrations.telegram.bot import TelegramBotService


@pytest.mark.asyncio
async def test_integrations_status_reports_unconfigured_gracefully(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/integrations")
    assert response.status_code == 200
    data = response.json()
    integrations = {item["provider"]: item for item in data["integrations"]}

    assert "google" in integrations
    assert "telegram" in integrations
    assert "n8n" in integrations
    assert isinstance(integrations["google"]["configured_in_env"], bool)


@pytest.mark.asyncio
async def test_google_connect_fails_gracefully_when_unconfigured(auth_client: AsyncClient):
    with patch.object(type(settings), "google_configured", new_callable=PropertyMock, return_value=False):
        response = await auth_client.post("/api/v1/integrations/google/connect")
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_telegram_connect_endpoint_or_graceful_response(auth_client: AsyncClient):
    response = await auth_client.post("/api/v1/integrations/telegram/connect")
    assert response.status_code in (200, 503)


def test_n8n_client_raises_when_not_configured():
    with patch.object(type(settings), "n8n_configured", new_callable=PropertyMock, return_value=False):
        client = N8nClient()
        with pytest.raises(IntegrationNotConfiguredError):
            client._ensure_configured()


@pytest.mark.asyncio
async def test_telegram_callback_query_approves_action_plan(db_session, test_user):
    """Verify that clicking the inline button in Telegram approves the ActionPlan."""
    planner = NexaPlanner(db_session)
    intent = ExtractedIntent(
        intent=IntentType.SCHEDULE_MEETING,
        confidence=1.0,
        entities={
            "topic": "Investor Demo",
            "client_name": "Angel Investor",
            "client_email": "angel@invest.com",
            "start_time": "2026-11-20T10:00:00Z",
            "end_time": "2026-11-20T11:00:00Z",
        },
    )
    plan = await planner.create_action_plan(intent, test_user)
    assert plan.status == ActionPlanStatus.pending_approval

    bot = TelegramBotService()

    # Mock external telegram HTTP calls
    with (
        patch.object(bot, "answer_callback_query", new_callable=AsyncMock) as mock_answer,
        patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send,
    ):
        update = {
            "callback_query": {
                "id": "query-12345",
                "data": f"approve:{plan.id}",
                "from": {"id": test_user.telegram_id},
                "message": {"chat": {"id": test_user.telegram_id}},
            }
        }
        await bot.handle_update(update, db_session)

        # Plan should now be approved
        await db_session.refresh(plan)
        assert plan.status == ActionPlanStatus.approved
        assert mock_answer.called
        assert mock_send.called
