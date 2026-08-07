"""FastAPI dependency providers for the tasks module.

`get_task_service` builds a `TaskService` from the request-scoped DB
session. `get_owned_task` resolves a task by its path id and verifies
it belongs to the current user, so `GET`/`PATCH`/`DELETE` handlers in
`router.py` never repeat that lookup or its not-found handling.
"""

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.modules.auth.models import User
from app.modules.auth.security import get_current_user
from app.modules.tasks.models import Task
from app.modules.tasks.service import TaskNotFoundError, TaskService


async def get_task_service(session: AsyncSession = Depends(get_db)) -> TaskService:
    """FastAPI dependency provider for `TaskService`."""
    return TaskService(session)


async def get_owned_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
) -> Task:
    """Resolve a task by id, ensuring it belongs to the current user."""
    try:
        return await service.get_owned(current_user.id, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found."
        ) from exc
