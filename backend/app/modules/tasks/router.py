"""HTTP routes for task CRUD, scoped to the authenticated user.

`DELETE` performs a soft delete: it archives the task (`status =
ARCHIVED`) rather than removing it, but still responds `204 No
Content` — from the caller's perspective the task disappears from
normal listings exactly as a hard delete would, while the row (and
everything future sprints attach to it) is preserved.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.modules.auth.models import User
from app.modules.auth.security import get_current_user
from app.modules.tasks.dependencies import get_owned_task, get_task_service
from app.modules.tasks.enums import TaskPriority, TaskStatus, TaskType
from app.modules.tasks.models import Task
from app.modules.tasks.schemas import TaskCreate, TaskRead, TaskUpdate
from app.modules.tasks.service import ProjectAccessDeniedError, TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])

_PROJECT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
)


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
) -> Task:
    """Create a new task within a project owned by the current user."""
    try:
        return await service.create(current_user.id, data)
    except ProjectAccessDeniedError as exc:
        raise _PROJECT_NOT_FOUND from exc


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    project_id: uuid.UUID | None = Query(default=None),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    task_type: TaskType | None = Query(default=None),
    priority: TaskPriority | None = Query(default=None),
    include_archived: bool = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
) -> list[Task]:
    """List the current user's tasks, optionally filtered. Archived tasks
    are excluded unless `include_archived=true` or `status=ARCHIVED` is
    explicitly requested."""
    try:
        return await service.list_for_owner(
            current_user.id,
            project_id=project_id,
            status=status_filter,
            task_type=task_type,
            priority=priority,
            include_archived=include_archived,
            skip=skip,
            limit=limit,
        )
    except ProjectAccessDeniedError as exc:
        raise _PROJECT_NOT_FOUND from exc


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task: Task = Depends(get_owned_task)) -> Task:
    """Fetch a single task owned by the current user (archived or not)."""
    return task


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    data: TaskUpdate,
    task: Task = Depends(get_owned_task),
    service: TaskService = Depends(get_task_service),
) -> Task:
    """Partially update a task owned by the current user."""
    return await service.update(task, data)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task: Task = Depends(get_owned_task),
    service: TaskService = Depends(get_task_service),
) -> None:
    """Archive (soft-delete) a task owned by the current user."""
    await service.archive(task)
