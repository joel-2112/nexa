"""Tasks repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, TaskStatus


class TaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, task_id: uuid.UUID, owner_id: uuid.UUID) -> Task | None:
        result = await self.db.execute(select(Task).where(Task.id == task_id, Task.owner_id == owner_id))
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        status: TaskStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Task], int]:
        query = select(Task).where(Task.owner_id == owner_id)
        count_query = select(func.count()).select_from(Task).where(Task.owner_id == owner_id)

        if status is not None:
            query = query.where(Task.status == status)
            count_query = count_query.where(Task.status == status)

        query = query.order_by(Task.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        count_result = await self.db.execute(count_query)
        tasks = list(result.scalars().all())
        total = count_result.scalar_one()
        return tasks, total

    async def create(
        self,
        owner_id: uuid.UUID,
        title: str,
        description: str | None,
        priority: str,
        due_at: datetime | None,
        source_conversation_id: uuid.UUID | None = None,
    ) -> Task:
        task = Task(
            owner_id=owner_id,
            title=title,
            description=description,
            priority=priority,
            due_at=due_at,
            source_conversation_id=source_conversation_id,
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def update(self, task: Task, **kwargs: object) -> Task:
        for k, v in kwargs.items():
            setattr(task, k, v)
        if kwargs.get("status") == TaskStatus.completed and task.completed_at is None:
            task.completed_at = datetime.now(UTC)
        await self.db.flush()
        return task

    async def delete(self, task: Task) -> None:
        await self.db.delete(task)
        await self.db.flush()
