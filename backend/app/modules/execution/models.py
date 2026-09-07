"""ExecutionJob ORM model -- durable state for the future execution launcher.

Phase 7B.7's design settled the Celery boundary question: the message a
future launcher task receives carries only `{"job_id": "<uuid>"}`, never a
serialized `LaunchRequest`/`ApprovedLaunchSpec`. Everything else must be
re-fetched from Postgres by that `job_id` and re-validated fresh (Phase
7B.7 Part 4/6). This model is that durable row -- its column set mirrors
`execution_launcher.models.LaunchRequest` field-for-field so a future slice
can reconstruct one from a row without guessing at a mapping.

`experiment_plan_id` is deliberately NOT a foreign key: `ExperimentPlan`
(`app.modules.research.experiment_schemas`) has no backing table yet, so a
real FK constraint here would reference a table that does not exist.
`input_asset_ids` is stored as JSONB (list of UUID strings), not a Postgres
`ARRAY`, to avoid the ARRAY-column/SQLite-test-environment landmine already
hit once in this project (`assets.tags`).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel
from app.modules.execution.enums import ExecutionAttemptStatus, ExecutionJobStatus
from execution_launcher.models import ExecutionCapability, ExecutionOperation, ResourceClass


def _enum_values(enum_cls: type) -> list[str]:
    """Persist enum members by their `.value`, not their `.name` (matches
    the tasks/assets/research modules' existing convention)."""
    return [member.value for member in enum_cls]


class ExecutionJob(BaseModel):
    """Durable record of a requested (not yet necessarily launched) execution."""

    __tablename__ = "execution_jobs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    experiment_plan_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    experiment_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)

    capability: Mapped[ExecutionCapability] = mapped_column(
        SQLEnum(ExecutionCapability, name="execution_capability_enum", native_enum=True, values_callable=_enum_values),
        nullable=False,
    )
    operation: Mapped[ExecutionOperation] = mapped_column(
        SQLEnum(ExecutionOperation, name="execution_operation_enum", native_enum=True, values_callable=_enum_values),
        nullable=False,
    )
    resource_class: Mapped[ResourceClass] = mapped_column(
        SQLEnum(ResourceClass, name="resource_class_enum", native_enum=True, values_callable=_enum_values),
        nullable=False,
    )
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    input_asset_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    status: Mapped[ExecutionJobStatus] = mapped_column(
        SQLEnum(ExecutionJobStatus, name="execution_job_status_enum", native_enum=True, values_callable=_enum_values),
        nullable=False,
        default=ExecutionJobStatus.PENDING,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExecutionAttempt(BaseModel):
    """Durable record of one concrete attempt to launch an `ExecutionJob`
    via Docker (Phase 7B.12 design, Part 3-8; implemented Phase 7B.13).

    Carries Docker IDENTITY only -- `container_name`/`container_id` --
    never Docker POLICY (image, command, network mode, privileged flag,
    environment, mounts). Policy lives entirely in
    `execution_launcher.models.ApprovedLaunchSpec`, produced fresh by the
    guard pipeline for every launch; this row exists so a future launcher
    and reconciler can answer "does a real container already correspond
    to this attempt" without guessing, per the Phase 7B.12 recovery
    protocol: `id` is generated and this row committed BEFORE any Docker
    call, `container_name` is a deterministic function of `id` persisted
    at the same time, and `container_id` stays NULL until a future slice
    confirms Docker actually created the container -- never populated
    here, never derived from `id`, never faked.
    """

    __tablename__ = "execution_attempts"
    __table_args__ = (
        # The one existing safety property a naive `max(attempt_number) + 1`
        # in application code cannot provide under concurrent writers: two
        # attempts for the same job can never persist with the same
        # number, no matter what raced to write them. This does not by
        # itself make retry-number *allocation* race-safe (a future
        # reconciler still needs its own claim before deciding the next
        # number to use, Phase 7B.12 Part 9) -- it only guarantees the
        # database rejects a collision if one is ever attempted.
        UniqueConstraint(
            "execution_job_id", "attempt_number", name="uq_execution_attempts_job_attempt_number"
        ),
    )

    execution_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Unique: Docker enforces name uniqueness within a daemon too, but the
    # database is the authoritative guard here, not a fallback -- two
    # attempt rows silently sharing a name would already have undermined
    # the recovery protocol before Docker ever got a chance to reject
    # anything (Phase 7B.12 Part "Container Name Uniqueness").
    container_name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # NULL until a future slice confirms Docker actually created the
    # container. Unique when present: one Docker container corresponds to
    # at most one attempt. Postgres treats multiple NULLs as distinct, so
    # any number of not-yet-created attempts can coexist.
    container_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)

    status: Mapped[ExecutionAttemptStatus] = mapped_column(
        SQLEnum(
            ExecutionAttemptStatus,
            name="execution_attempt_status_enum",
            native_enum=True,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=ExecutionAttemptStatus.PENDING_CREATE,
        # Indexed for the same reason `ResearchRun.status` is: a future
        # reconciler scans for attempts stuck at `PENDING_CREATE` past a
        # staleness threshold (mirroring
        # `app.workers.reconciliation.reconcile_stale_research_runs`) --
        # not built in this slice, but the query shape is already known.
        index=True,
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
