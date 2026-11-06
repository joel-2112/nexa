"""Tests for task management and user data isolation."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user_id
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app


@pytest.mark.asyncio
async def test_task_crud_lifecycle(auth_client: AsyncClient):
    # 1. Create task
    create_res = await auth_client.post(
        "/api/v1/tasks",
        json={
            "title": "Prepare financial projection",
            "description": "Draft Q4 metrics for executive board",
            "priority": "high",
        },
    )
    assert create_res.status_code == 201
    task = create_res.json()
    task_id = task["id"]
    assert task["title"] == "Prepare financial projection"
    assert task["status"] == "pending"

    # 2. Get task
    get_res = await auth_client.get(f"/api/v1/tasks/{task_id}")
    assert get_res.status_code == 200
    assert get_res.json()["priority"] == "high"

    # 3. Update task status
    patch_res = await auth_client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "completed"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "completed"

    # 4. Delete task
    del_res = await auth_client.delete(f"/api/v1/tasks/{task_id}")
    assert del_res.status_code == 204

    # 5. Verify deleted
    verify_res = await auth_client.get(f"/api/v1/tasks/{task_id}")
    assert verify_res.status_code == 404


@pytest.mark.asyncio
async def test_user_data_isolation_on_tasks(auth_client: AsyncClient, test_user, other_user, db_session):
    """Ensure User B cannot read or modify User A's task."""
    # User A creates a confidential task
    create_res = await auth_client.post(
        "/api/v1/tasks",
        json={"title": "User A Private Strategy Task"},
    )
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]

    # Now create an AsyncClient for User B
    async def override_get_db():
        yield db_session

    async def override_get_current_user_id():
        return other_user.id

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = override_get_current_user_id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as other_client:
        token = create_access_token(other_user.id)
        other_client.headers.update({"Authorization": f"Bearer {token}"})

        # User B attempts to access User A's task -> should be 404 (isolated)
        forbidden_get = await other_client.get(f"/api/v1/tasks/{task_id}")
        assert forbidden_get.status_code == 404

        # User B attempts to update User A's task
        forbidden_patch = await other_client.patch(f"/api/v1/tasks/{task_id}", json={"status": "completed"})
        assert forbidden_patch.status_code == 404

    # Restore original overrides
    app.dependency_overrides.clear()
