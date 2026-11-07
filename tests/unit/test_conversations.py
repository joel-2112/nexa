"""Tests for conversation persistence and contextual memory."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_fetch_conversation(auth_client: AsyncClient):
    create_res = await auth_client.post("/api/v1/conversations", json={"title": "Client Strategy Session"})
    assert create_res.status_code == 201
    conv = create_res.json()
    conv_id = conv["id"]
    assert conv["title"] == "Client Strategy Session"

    # Fetch detail
    get_res = await auth_client.get(f"/api/v1/conversations/{conv_id}")
    assert get_res.status_code == 200
    detail = get_res.json()
    assert detail["id"] == conv_id
    assert len(detail["messages"]) == 0


@pytest.mark.asyncio
async def test_contextual_meeting_follow_up_workflow(auth_client: AsyncClient):
    """Verify that NEXA asks follow-up questions when details are missing."""
    # 1. Start conversation
    create_res = await auth_client.post("/api/v1/conversations", json={"title": "Meeting Setup"})
    conv_id = create_res.json()["id"]

    # 2. User provides initial partial statement: "Tomorrow at 10 AM, I have a meeting about fintech."
    # Missing: client name, email, duration
    msg1_res = await auth_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Tomorrow at 10 AM, I have a meeting with a client about our fintech project."},
    )
    assert msg1_res.status_code == 201
    data1 = msg1_res.json()
    assert data1["clarification_needed"] is True
    assert len(data1["follow_up_questions"]) > 0

    # 3. User answers client name: "John Smith"
    msg2_res = await auth_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "The client is John Smith"},
    )
    assert msg2_res.status_code == 201
    data2 = msg2_res.json()
    assert data2["clarification_needed"] is True

    # 4. User provides email and duration
    msg3_res = await auth_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "His email is john@example.com and the meeting is for 1 hour."},
    )
    assert msg3_res.status_code == 201
    data3 = msg3_res.json()
    # Now that all info is gathered, an action plan is proposed and approval is requested!
    assert data3["action_plan_id"] is not None


@pytest.mark.asyncio
async def test_task_and_reminder_creation_workflow(auth_client: AsyncClient):
    """Verify that NEXA creates a task and schedules a reminder from relative time statements."""
    create_res = await auth_client.post("/api/v1/conversations", json={"title": "Task Planning"})
    conv_id = create_res.json()["id"]

    msg_res = await auth_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "after 20 minutes i will have the task to check my email"},
    )
    assert msg_res.status_code == 201
    data = msg_res.json()
    assert data["action_plan_id"] is not None
    assert "Check my email" in data["message"]["content"]
    assert "Schedule Telegram notification" in data["message"]["content"]
    assert "action plan" in data["message"]["content"].lower()


@pytest.mark.asyncio
async def test_relative_offset_meeting_workflow(auth_client: AsyncClient):
    """Verify that NEXA accepts 'in 20 minutes' for scheduling meetings directly."""
    create_res = await auth_client.post("/api/v1/conversations", json={"title": "Quick Meeting"})
    conv_id = create_res.json()["id"]

    msg_res = await auth_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "in 20 minutes schedule a meeting with client John (john@example.com) about the fintech project"},
    )
    assert msg_res.status_code == 201
    data = msg_res.json()
    assert data["action_plan_id"] is not None
    assert "Meeting with" in data["message"]["content"]
    assert "fintech project" in data["message"]["content"]
    assert "Check calendar availability" in data["message"]["content"]
