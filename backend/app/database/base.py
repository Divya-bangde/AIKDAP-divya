"""Declarative base and shared abstract model for SQLAlchemy 2.x ORM models.

Concrete application models (added in later sprints) should inherit from
`BaseModel` rather than `Base` directly, to get a consistent UUID primary
key and audit timestamps across the schema.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Fixed naming convention so Alembic autogenerate produces deterministic,
# readable constraint/index names instead of database-assigned ones.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models in the application."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class BaseModel(Base):
    """Abstract base providing a UUID primary key and audit timestamps."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
