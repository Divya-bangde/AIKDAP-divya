"""Pydantic v2 request/response schemas for the projects module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.projects.models import ProjectStatus, ProjectType


class ProjectCreate(BaseModel):
    """Payload for creating a new project."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    project_type: ProjectType = ProjectType.RESEARCH
    color: str | None = Field(default=None, max_length=20)
    icon: str | None = Field(default=None, max_length=50)


class ProjectUpdate(BaseModel):
    """Payload for partially updating a project. Unset fields are left untouched."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    project_type: ProjectType | None = None
    status: ProjectStatus | None = None
    color: str | None = Field(default=None, max_length=20)
    icon: str | None = Field(default=None, max_length=50)


class ProjectRead(BaseModel):
    """Public representation of a project."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    project_type: ProjectType
    status: ProjectStatus
    color: str | None
    icon: str | None
    created_at: datetime
    updated_at: datetime
