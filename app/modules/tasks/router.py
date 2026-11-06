"""Tasks API router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import NotFoundError, http_not_found
from app.db.models import TaskStatus
from app.modules.tasks.schemas import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)
from app.modules.tasks.service import TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    user_id: CurrentUserId,
    db: DbSession,
) -> TaskResponse:
    svc = TaskService(db)
    return await svc.create_task(user_id, payload)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    user_id: CurrentUserId,
    db: DbSession,
    status: TaskStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> TaskListResponse:
    svc = TaskService(db)
    return await svc.list_tasks(user_id, status, page, page_size)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, user_id: CurrentUserId, db: DbSession) -> TaskResponse:
    svc = TaskService(db)
    try:
        return await svc.get_task(task_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: UUID, payload: TaskUpdate, user_id: CurrentUserId, db: DbSession) -> TaskResponse:
    svc = TaskService(db)
    try:
        return await svc.update_task(task_id, user_id, payload)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: UUID, user_id: CurrentUserId, db: DbSession) -> None:
    svc = TaskService(db)
    try:
        await svc.delete_task(task_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.detail)
