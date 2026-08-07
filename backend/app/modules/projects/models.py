"""Project ORM model — the central workspace entity every other domain
(Assets, Knowledge Base, Workspace Memory, Research, Business Analytics,
LangGraph runs) will belong to.
"""

import enum
import uuid

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class ProjectType(str, enum.Enum):
    """The kind of work a project is oriented around."""

    RESEARCH = "research"
    BUSINESS = "business"
    HYBRID = "hybrid"


class ProjectStatus(str, enum.Enum):
    """Lifecycle state of a project."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class Project(BaseModel):
    """A user-owned workspace that all other project-scoped data belongs to."""

    __tablename__ = "projects"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_type: Mapped[ProjectType] = mapped_column(
        SQLEnum(
            ProjectType,
            name="project_type_enum",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ProjectType.RESEARCH,
    )
    status: Mapped[ProjectStatus] = mapped_column(
        SQLEnum(
            ProjectStatus,
            name="project_status_enum",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ProjectStatus.ACTIVE,
    )
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
