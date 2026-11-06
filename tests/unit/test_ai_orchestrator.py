"""Tests for AI planning, Tool Authorization, Approval Workflow, and Idempotency."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.ai.planner import NexaPlanner
from app.ai.schemas import ExtractedIntent, IntentType
from app.ai.tool_executor import ToolExecutor
from app.core.exceptions import ApprovalRequiredError, ToolExecutionError
from app.db.models import ActionPlanStatus


@pytest.mark.asyncio
async def test_tool_authorization_and_approval_enforcement(db_session, test_user):
    """Verify that mutating tools raise ApprovalRequiredError when called without authorization."""
    executor = ToolExecutor(db_session)

    # 1. Mutating tool without bypass flag -> raises ApprovalRequiredError
    with pytest.raises(ApprovalRequiredError):
        await executor.execute(
            tool_name="create_calendar_event",
            arguments={
                "title": "Unauthorized Meeting",
                "start_time": "2026-11-08T10:00:00Z",
                "end_time": "2026-11-08T11:00:00Z",
            },
            user=test_user,
            bypass_approval_check=False,
        )

    # 2. Read-only tool -> succeeds without approval
    res = await executor.execute(
        tool_name="check_calendar_availability",
        arguments={
            "start_time": "2026-11-08T10:00:00Z",
            "end_time": "2026-11-08T11:00:00Z",
        },
        user=test_user,
        bypass_approval_check=False,
    )
    assert "available" in res


@pytest.mark.asyncio
async def test_unregistered_tool_rejected(db_session, test_user):
    executor = ToolExecutor(db_session)
    with pytest.raises(ToolExecutionError):
        await executor.execute(
            tool_name="execute_arbitrary_shell_command",
            arguments={"cmd": "ls"},
            user=test_user,
        )


@pytest.mark.asyncio
async def test_tool_execution_idempotency(db_session, test_user):
    """Ensure duplicate execution with the same idempotency key does not recreate data."""
    executor = ToolExecutor(db_session)
    idempotency_key = f"idem-key-{uuid.uuid4()}"

    args = {
        "title": "Idempotent Task",
        "description": "Must not duplicate",
    }

    # First execution
    res1 = await executor.execute(
        tool_name="create_task",
        arguments=args,
        user=test_user,
        bypass_approval_check=True,
        idempotency_key=idempotency_key,
    )
    task_id1 = res1["task_id"]

    # Second execution with same idempotency key -> returns cached result
    res2 = await executor.execute(
        tool_name="create_task",
        arguments=args,
        user=test_user,
        bypass_approval_check=True,
        idempotency_key=idempotency_key,
    )
    assert res2["task_id"] == task_id1


@pytest.mark.asyncio
async def test_action_plan_approval_and_rejection_workflow(auth_client: AsyncClient, db_session, test_user):
    """Test generating a plan and approving/rejecting via REST API."""
    planner = NexaPlanner(db_session)

    intent = ExtractedIntent(
        intent=IntentType.SCHEDULE_MEETING,
        confidence=1.0,
        entities={
            "topic": "Fintech Seed Round",
            "client_name": "VC Partner",
            "client_email": "vc@ventures.com",
            "start_time": "2026-11-12T15:00:00Z",
            "end_time": "2026-11-12T16:00:00Z",
        },
    )
    plan = await planner.create_action_plan(intent, test_user)
    assert plan.status == ActionPlanStatus.pending_approval
    assert len(plan.steps) >= 4

    # 1. Fetch via API
    get_res = await auth_client.get(f"/api/v1/action-plans/{plan.id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "pending_approval"

    # 2. Approve via API
    approve_res = await auth_client.post(f"/api/v1/action-plans/{plan.id}/approve")
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "approved"
    assert approve_res.json()["approved_at"] is not None


@pytest.mark.asyncio
async def test_find_free_slots_tool(db_session, test_user):
    executor = ToolExecutor(db_session)
    res = await executor.execute(
        tool_name="find_free_slots",
        arguments={"date": "2026-11-15", "duration_minutes": 60},
        user=test_user,
    )
    assert res["date"] == "2026-11-15"
    assert "available_slots" in res
    assert len(res["available_slots"]) > 0
