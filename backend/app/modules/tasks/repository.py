"""Data-access layer for the `Task` model.

Contains only persistence operations; transaction boundaries (commit),
ownership rules, and the soft-delete (archive) policy live in
`service.py`. There is deliberately no `delete()` method here — tasks
are never physically removed, only archived via a normal update.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.enums import TaskPriority, TaskStatus, TaskType
from app.modules.tasks.models import Task


class TaskRepository:
    """Encapsulates all direct database access for `Task` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        """Fetch a task by primary key, or None if not found."""
        return await self._session.get(Task, task_id)

    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        status: TaskStatus | None = None,
        task_type: TaskType | None = None,
        priority: TaskPriority | None = None,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Task]:
        """List tasks owned by a user, with optional filters.

        Archived tasks are excluded by default (soft delete should make
        a task disappear from normal views) unless `include_archived`
        is set or the caller explicitly filters for `status=ARCHIVED`.
        """
        stmt = select(Task).where(Task.owner_id == owner_id)

        if not include_archived and status is None:
            stmt = stmt.where(Task.status != TaskStatus.ARCHIVED)
        if project_id is not None:
            stmt = stmt.where(Task.project_id == project_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if task_type is not None:
            stmt = stmt.where(Task.task_type == task_type)
        if priority is not None:
            stmt = stmt.where(Task.priority == priority)

        stmt = stmt.order_by(Task.created_at.desc()).offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, task: Task) -> Task:
        """Insert a new task row and flush to populate generated fields."""
        self._session.add(task)
        await self._session.flush()
        await self._session.refresh(task)
        return task
