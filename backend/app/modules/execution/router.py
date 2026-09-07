"""HTTP routes for the execution module (Sprint 16 Phase 7B.23).

Read-only: listing/inspecting `ExecutionJob` rows and their attempts.
There is no `POST` here that accepts a caller-supplied job payload --
the only way to create one is `POST /research/experiments/{plan_id}/execute`
(the plan lives in the research module, and the mapping from a plan to a
job is real design work that belongs next to the plan, not a raw
`ExecutionJobCreate` this router would otherwise have to trust blindly).

Ownership is enforced directly against `ExecutionJob.owner_id` (see
`service.get_owned_job`'s docstring for why that is equivalent to going
through the project) -- "not yours" and "does not exist" are
indistinguishable from the outside, matching every other module.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.modules.auth.models import User
from app.modules.auth.security import get_current_user
from app.modules.execution.models import ExecutionJob
from app.modules.execution.repository import ExecutionAttemptRepository
from app.modules.execution.schemas import ExecutionAttemptRead, ExecutionJobDetail, ExecutionJobRead
from app.modules.execution.service import ExecutionJobNotFoundError, get_owned_job, list_owned_jobs

router = APIRouter(prefix="/execution", tags=["Execution"])

_EXECUTION_JOB_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Execution job not found."
)


@router.get("/jobs", response_model=list[ExecutionJobRead])
async def list_execution_jobs_route(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[ExecutionJob]:
    """List the current user's execution jobs, newest first."""
    return await list_owned_jobs(current_user.id, session)


@router.get("/jobs/{job_id}", response_model=ExecutionJobDetail)
async def get_execution_job_route(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ExecutionJobDetail:
    """Fetch one job together with every attempt made against it."""
    try:
        job = await get_owned_job(current_user.id, job_id, session)
    except ExecutionJobNotFoundError as exc:
        raise _EXECUTION_JOB_NOT_FOUND from exc

    attempts = await ExecutionAttemptRepository(session).list_by_job(job.id)
    return ExecutionJobDetail(
        **ExecutionJobRead.model_validate(job).model_dump(),
        attempts=[ExecutionAttemptRead.model_validate(attempt) for attempt in attempts],
    )
