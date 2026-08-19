"""Pydantic v2 request/response schemas for the research module.

`plan`, `objective`, `final_answer`, `citations`, and every timing field
are read-only: they are produced by the workflow, never supplied by the
caller. The only thing a client sends is what to research and where to
look.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.research.enums import (
    AgentMessageRole,
    ResearchGroundingStatus,
    ResearchRunStatus,
    ResearchStepStatus,
)
from app.modules.research.models import AgentMessage, ResearchRun


class ResearchRunCreate(BaseModel):
    """Payload for starting a research run."""

    project_id: uuid.UUID
    query: str = Field(min_length=3, max_length=20_000)
    # Optional association with an existing task, validated for
    # ownership like the project is.
    task_id: uuid.UUID | None = None
    include_assets: bool = Field(
        default=True, description="Search the project's own knowledge base."
    )
    include_web: bool = Field(
        default=True, description="Gather external references (simulated in this release)."
    )
    max_results: int = Field(default=5, ge=1, le=20)


class ResearchRunAccepted(BaseModel):
    """Immediate `201` response: the run exists, execution has been queued.

    Deliberately small. The workflow has not started when this is
    returned, so anything it produces would be a lie at this point —
    poll `GET /research/runs/{run_id}` for results.
    """

    run_id: uuid.UUID
    status: ResearchRunStatus
    project_id: uuid.UUID
    query: str
    created_at: datetime

    @classmethod
    def from_model(cls, run: ResearchRun) -> "ResearchRunAccepted":
        """Build the acceptance response from the freshly created run."""
        return cls(
            run_id=run.id,
            status=run.status,
            project_id=run.project_id,
            query=run.query,
            created_at=run.created_at,
        )


class ResearchRunRead(BaseModel):
    """Full state of a research run."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    owner_id: uuid.UUID
    task_id: uuid.UUID | None
    query: str
    status: ResearchRunStatus
    include_assets: bool
    include_web: bool
    max_results: int
    objective: str | None
    plan: dict[str, Any] | None
    final_answer: str | None
    citations: list[dict[str, Any]] | None
    #: How well `final_answer` is supported by the cited evidence.
    #: `None` when the run never reached synthesis. Distinct from
    #: `status`: a run can be `completed` and
    #: `insufficient_evidence` at the same time, which is the honest
    #: answer to an unanswerable question.
    grounding_status: ResearchGroundingStatus | None
    error_message: str | None
    celery_task_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime


class ResearchStepRead(BaseModel):
    """One node's execution record within a run."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    step_index: int
    node_name: str
    title: str
    status: ResearchStepStatus
    summary: str | None
    output_payload: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime


class AgentMessageRead(BaseModel):
    """One agent transcript entry within a run."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    step_id: uuid.UUID | None
    sequence: int
    role: AgentMessageRole
    agent_name: str
    content: str
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_model(cls, message: AgentMessage) -> "AgentMessageRead":
        """Build the response from an ORM row.

        Bridges the `message_metadata` attribute back to the `metadata`
        field the API exposes (see the note in `models.AgentMessage`).
        """
        return cls(
            id=message.id,
            run_id=message.run_id,
            step_id=message.step_id,
            sequence=message.sequence,
            role=message.role,
            agent_name=message.agent_name,
            content=message.content,
            metadata=message.message_metadata,
            created_at=message.created_at,
        )


class ResearchRunDetail(ResearchRunRead):
    """A run together with its full Explainable-AI trace."""

    steps: list[ResearchStepRead] = Field(default_factory=list)
    messages: list[AgentMessageRead] = Field(default_factory=list)
