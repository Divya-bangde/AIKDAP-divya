"""Task ORM model — a unit of work inside a Project.

Every future AI execution (Planner, LangGraph, Agents) attaches to a
Task. `planner_output`, `estimated_cost`, `estimated_tokens`,
`started_at`, and `completed_at` are groundwork columns for that future
work; nothing in this sprint populates them.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel
from app.modules.tasks.enums import TaskPriority, TaskStatus, TaskType


def _enum_values(enum_cls: type) -> list[str]:
    """Persist enum members by their `.value`, not their `.name`.

    SQLAlchemy's `Enum` defaults to storing Python enum names rather
    than `.value`s unless told otherwise; kept consistent with the
    projects/assets modules even though name and value are identical
    here, so the database enum never silently diverges from the wire
    values if either ever changes.
    """
    return [member.value for member in enum_cls]


class Task(BaseModel):
    """A unit of work inside a project that future AI execution attaches to."""

    __tablename__ = "tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    task_type: Mapped[TaskType] = mapped_column(
        SQLEnum(TaskType, name="task_type_enum", native_enum=True, values_callable=_enum_values),
        nullable=False,
    )
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus, name="task_status_enum", native_enum=True, values_callable=_enum_values),
        nullable=False,
        default=TaskStatus.DRAFT,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        SQLEnum(TaskPriority, name="task_priority_enum", native_enum=True, values_callable=_enum_values),
        nullable=False,
        default=TaskPriority.MEDIUM,
    )

    planner_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    estimated_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
