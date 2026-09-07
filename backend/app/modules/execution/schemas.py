"""Pydantic v2 schemas for the execution module.

`status`, `reason`, `started_at`, and `completed_at` are deliberately
absent from `ExecutionJobCreate`, matching `TaskCreate`'s exclusion of
its own future-execution columns: they are outputs of a future launcher,
not something set at job-creation time. They're read-only in
`ExecutionJobRead`.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.execution.enums import ExecutionAttemptStatus, ExecutionJobStatus
from execution_launcher.models import ExecutionCapability, ExecutionOperation, LaunchParameterValue, ResourceClass


class ExecutionJobCreate(BaseModel):
    """Payload for persisting a new execution job."""

    project_id: uuid.UUID
    owner_id: uuid.UUID
    experiment_plan_id: uuid.UUID
    experiment_plan_version: int = Field(ge=1)
    capability: ExecutionCapability
    operation: ExecutionOperation
    resource_class: ResourceClass
    parameters: dict[str, LaunchParameterValue] = Field(default_factory=dict)
    input_asset_ids: list[uuid.UUID] = Field(default_factory=list)


class ExecutionJobRead(BaseModel):
    """Public representation of a persisted execution job."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    owner_id: uuid.UUID
    experiment_plan_id: uuid.UUID
    experiment_plan_version: int
    capability: ExecutionCapability
    operation: ExecutionOperation
    resource_class: ResourceClass
    parameters: dict[str, Any]
    input_asset_ids: list[uuid.UUID]
    status: ExecutionJobStatus
    reason: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExecutionAttemptCreate(BaseModel):
    """Payload for persisting a new execution attempt.

    `status`, `container_id`, `exit_code`, `error_message`, `started_at`,
    and `completed_at` are deliberately absent -- same rationale as
    `ExecutionJobCreate`'s exclusions: they are outputs of a future
    launcher/reconciler, not something set at attempt-creation time.
    `container_name` IS required here: a future service computes it
    deterministically from the attempt's id before any Docker call
    (Phase 7B.12 Part 5), but this schema only defines its storage, not
    that computation.
    """

    execution_job_id: uuid.UUID
    attempt_number: int = Field(ge=1)
    container_name: str = Field(min_length=1, max_length=255)


class ExecutionAttemptRead(BaseModel):
    """Public representation of a persisted execution attempt."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_job_id: uuid.UUID
    attempt_number: int
    container_name: str
    container_id: str | None
    status: ExecutionAttemptStatus
    exit_code: int | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExecutionJobDetail(ExecutionJobRead):
    """`ExecutionJobRead` plus its attempts (Sprint 16 Phase 7B.23) --
    `GET /execution/jobs/{job_id}` only; the list route stays lightweight
    and returns bare `ExecutionJobRead` rows, matching
    `ResearchRunRead`/`ResearchRunDetail`'s existing list-vs-detail split."""

    attempts: list[ExecutionAttemptRead]
