"""Pydantic v2 request/response schemas for the tasks module.

`planner_output`, `estimated_cost`, `estimated_tokens`, `started_at`,
and `completed_at` are deliberately absent from `TaskCreate`/`TaskUpdate`:
they are outputs of a future execution engine (Planner/LangGraph), not
something a task's owner sets directly. They're read-only in `TaskRead`.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.tasks.enums import TaskPriority, TaskStatus, TaskType


class TaskCreate(BaseModel):
    """Payload for creating a new task within a project."""

    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    input_prompt: str = Field(min_length=1, max_length=20000)
    task_type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM


class TaskUpdate(BaseModel):
    """Payload for partially updating a task. Unset fields are left untouched."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    input_prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    task_type: TaskType | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None


class TaskRead(BaseModel):
    """Public representation of a task."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    description: str | None
    input_prompt: str
    task_type: TaskType
    status: TaskStatus
    priority: TaskPriority
    planner_output: dict[str, Any] | None
    estimated_cost: Decimal | None
    estimated_tokens: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
