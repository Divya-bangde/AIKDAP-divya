"""HTTP routes for the research workspace, scoped to the authenticated user.

`POST /research/run` is asynchronous by contract: it validates the
request, creates the run, dispatches it to the Celery worker, and
returns `202`-style acceptance semantics with a `201` status (the run
resource genuinely was created). No part of the workflow executes
inside the request.

The two `GET` routes are what make that contract usable — without a way
to read a run back, an endpoint that only ever returns "pending" would
be inert. `GET /research/runs/{id}` returns the full Explainable-AI
trace: the plan, every node's execution record, and the agent
transcript.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.modules.auth.models import User
from app.modules.auth.security import get_current_user
from app.modules.research.dependencies import get_owned_run, get_research_service
from app.modules.research.enums import ResearchRunStatus
from app.modules.research.models import ResearchRun
from app.modules.research.schemas import (
    AgentMessageRead,
    ResearchRunAccepted,
    ResearchRunCreate,
    ResearchRunDetail,
    ResearchRunRead,
    ResearchStepRead,
)
from app.modules.research.service import (
    ProjectAccessDeniedError,
    ResearchService,
    TaskAccessDeniedError,
)

router = APIRouter(prefix="/research", tags=["Research"])

_PROJECT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
)
_TASK_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Task not found."
)


@router.post("/run", response_model=ResearchRunAccepted, status_code=status.HTTP_201_CREATED)
async def start_research_run(
    data: ResearchRunCreate,
    current_user: User = Depends(get_current_user),
    service: ResearchService = Depends(get_research_service),
) -> ResearchRunAccepted:
    """Start a research run and return immediately with its id and status.

    The LangGraph workflow runs in the Celery worker; poll
    `GET /research/runs/{run_id}` for the plan, trace, and final answer.
    """
    try:
        run = await service.start_run(current_user.id, data)
    except ProjectAccessDeniedError as exc:
        raise _PROJECT_NOT_FOUND from exc
    except TaskAccessDeniedError as exc:
        raise _TASK_NOT_FOUND from exc
    return ResearchRunAccepted.from_model(run)


@router.get("/runs", response_model=list[ResearchRunRead])
async def list_research_runs(
    project_id: uuid.UUID | None = Query(default=None),
    status_filter: ResearchRunStatus | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    service: ResearchService = Depends(get_research_service),
) -> list[ResearchRun]:
    """List the current user's research runs, newest first."""
    try:
        return await service.list_runs(
            current_user.id,
            project_id=project_id,
            status=status_filter,
            skip=skip,
            limit=limit,
        )
    except ProjectAccessDeniedError as exc:
        raise _PROJECT_NOT_FOUND from exc


@router.get("/runs/{run_id}", response_model=ResearchRunDetail)
async def get_research_run(
    run: ResearchRun = Depends(get_owned_run),
    service: ResearchService = Depends(get_research_service),
) -> ResearchRunDetail:
    """Fetch one run with its full execution trace and agent transcript."""
    steps, messages = await service.get_trace(run)
    return ResearchRunDetail(
        **ResearchRunRead.model_validate(run).model_dump(),
        steps=[ResearchStepRead.model_validate(step) for step in steps],
        # `AgentMessage` needs the explicit bridge from its
        # `message_metadata` attribute to the `metadata` API field.
        messages=[AgentMessageRead.from_model(message) for message in messages],
    )
