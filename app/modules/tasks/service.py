"""Tasks service layer."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import TaskStatus
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskListResponse, TaskResponse, TaskUpdate


class TaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = TaskRepository(db)

    async def create_task(self, owner_id: uuid.UUID, payload: TaskCreate) -> TaskResponse:
        task = await self.repo.create(
            owner_id=owner_id,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            due_at=payload.due_at,
        )
        return TaskResponse.model_validate(task)

    async def list_tasks(
        self,
        owner_id: uuid.UUID,
        status: TaskStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TaskListResponse:
        tasks, total = await self.repo.list_for_user(owner_id, status, page, page_size)
        return TaskListResponse(
            items=[TaskResponse.model_validate(t) for t in tasks],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_task(self, task_id: uuid.UUID, owner_id: uuid.UUID) -> TaskResponse:
        task = await self.repo.get_by_id(task_id, owner_id)
        if task is None:
            raise NotFoundError("Task not found")
        return TaskResponse.model_validate(task)

    async def update_task(self, task_id: uuid.UUID, owner_id: uuid.UUID, payload: TaskUpdate) -> TaskResponse:
        task = await self.repo.get_by_id(task_id, owner_id)
        if task is None:
            raise NotFoundError("Task not found")
        updates = payload.model_dump(exclude_unset=True)
        task = await self.repo.update(task, **updates)
        return TaskResponse.model_validate(task)

    async def delete_task(self, task_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        task = await self.repo.get_by_id(task_id, owner_id)
        if task is None:
            raise NotFoundError("Task not found")
        await self.repo.delete(task)
