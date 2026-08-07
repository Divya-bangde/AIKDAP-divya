"""Business logic for task creation, retrieval, update, and archival.

Ownership is enforced transitively: a task belongs to a project, and a
user may only touch tasks in projects they own. As with the projects
and assets modules, "exists but not yours" and "doesn't exist" both
surface as `TaskNotFoundError` so ownership is never leaked. Deletion
is a soft delete: `archive()` sets `status=ARCHIVED` rather than
removing the row, since every future Planner/LangGraph/Agent run,
memory entry, timeline event, and report will reference tasks by id.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.enums import TaskPriority, TaskStatus, TaskType
from app.modules.tasks.models import Task
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskUpdate
from app.modules.projects.repository import ProjectRepository


class TaskNotFoundError(Exception):
    """Raised when a task does not exist or is not owned by the caller."""


class ProjectAccessDeniedError(Exception):
    """Raised when the caller does not own the project a task belongs to."""


class TaskService:
    """Coordinates task creation, retrieval, updates, listing, and archival."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = TaskRepository(session)
        self._projects = ProjectRepository(session)

    async def _ensure_project_owned(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> None:
        project = await self._projects.get_by_id(project_id)
        if project is None or project.owner_id != owner_id:
            raise ProjectAccessDeniedError(project_id)

    async def create(self, owner_id: uuid.UUID, data: TaskCreate) -> Task:
        """Create a new task, validating the caller owns the target project."""
        await self._ensure_project_owned(owner_id, data.project_id)

        task = Task(
            project_id=data.project_id,
            owner_id=owner_id,
            title=data.title,
            description=data.description,
            input_prompt=data.input_prompt,
            task_type=data.task_type,
            status=TaskStatus.DRAFT,
            priority=data.priority,
        )
        created = await self._repository.create(task)
        await self._session.commit()
        return created

    async def get_owned(self, owner_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        """Fetch a task, ensuring it belongs to the given user."""
        task = await self._repository.get_by_id(task_id)
        if task is None or task.owner_id != owner_id:
            raise TaskNotFoundError(task_id)
        return task

    async def list_for_owner(
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
        """List the current user's tasks, optionally filtered."""
        if project_id is not None:
            await self._ensure_project_owned(owner_id, project_id)
        return await self._repository.list_by_owner(
            owner_id,
            project_id=project_id,
            status=status,
            task_type=task_type,
            priority=priority,
            include_archived=include_archived,
            skip=skip,
            limit=limit,
        )

    async def update(self, task: Task, data: TaskUpdate) -> Task:
        """Apply a partial update to an already-authorized task."""
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(task, field, value)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def archive(self, task: Task) -> Task:
        """Soft-delete an already-authorized task by marking it archived."""
        task.status = TaskStatus.ARCHIVED
        await self._session.commit()
        await self._session.refresh(task)
        return task
