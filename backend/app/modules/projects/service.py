"""Business logic for creating, listing, and managing projects.

Ownership is enforced here: a project that exists but belongs to a
different user is treated identically to one that doesn't exist, so
`ProjectNotFoundError` covers both cases and the router never leaks
which one occurred.
"""

import uuid

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


class ProjectNotFoundError(Exception):
    """Raised when a project does not exist or is not owned by the caller."""


class ProjectService:
    """Coordinates project creation, retrieval, updates, and deletion."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ProjectRepository(session)

    async def create(self, owner_id: uuid.UUID, data: ProjectCreate) -> Project:
        """Create a new project owned by the given user."""
        project = await self._repository.create(
            owner_id=owner_id,
            name=data.name,
            description=data.description,
            project_type=data.project_type,
            color=data.color,
            icon=data.icon,
        )
        await self._session.commit()
        return project

    async def list_for_owner(
        self, owner_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> list[Project]:
        """List all projects owned by the given user."""
        return await self._repository.list_by_owner(owner_id, skip=skip, limit=limit)

    async def get_owned(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> Project:
        """Fetch a project, ensuring it belongs to the given user."""
        project = await self._repository.get_by_id(project_id)
        if project is None or project.owner_id != owner_id:
            raise ProjectNotFoundError(project_id)
        return project

    async def update(
        self, owner_id: uuid.UUID, project_id: uuid.UUID, data: ProjectUpdate
    ) -> Project:
        """Apply a partial update to a project owned by the given user."""
        project = await self.get_owned(owner_id, project_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        await self._session.commit()
        await self._session.refresh(project)
        return project

    async def delete(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> None:
        """Delete a project owned by the given user."""
        project = await self.get_owned(owner_id, project_id)
        await self._repository.delete(project)
        await self._session.commit()


async def get_project_service(session: AsyncSession = Depends(get_db)) -> ProjectService:
    """FastAPI dependency provider for `ProjectService`."""
    return ProjectService(session)
