"""Tests for calendar management."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_calendar_event_lifecycle(auth_client: AsyncClient):
    # 1. Create Event
    payload = {
        "title": "Quarterly Financial Sync",
        "description": "Review ARR and churn metrics",
        "start_at": "2026-11-10T14:00:00Z",
        "end_at": "2026-11-10T15:00:00Z",
        "location": "Boardroom / Meet",
        "participants": [{"email": "partner@fintech.com", "full_name": "Senior Partner"}],
    }
    create_res = await auth_client.post("/api/v1/calendar/events", json=payload)
    assert create_res.status_code == 201
    event = create_res.json()
    event_id = event["id"]
    assert event["title"] == "Quarterly Financial Sync"
    assert event["status"] == "scheduled"
    assert len(event["participants"]) == 1

    # 2. List Events with range filter
    list_res = await auth_client.get(
        "/api/v1/calendar/events?start_min=2026-11-10T00:00:00Z&start_max=2026-11-11T00:00:00Z"
    )
    assert list_res.status_code == 200
    events = list_res.json()["items"]
    assert any(e["id"] == event_id for e in events)

    # 3. Cancel Event
    del_res = await auth_client.delete(f"/api/v1/calendar/events/{event_id}")
    assert del_res.status_code == 204
