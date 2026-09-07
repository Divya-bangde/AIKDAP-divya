"""Reconstructs a `LaunchRequest` from persisted `ExecutionJob` state, and
orchestrates that reconstruction through the existing guard pipeline.

The bridge Phase 7B.7's design settled on: a future launcher's Celery
message carries only `{"job_id": "<uuid>"}`, never a serialized
`LaunchRequest`/`ApprovedLaunchSpec` -- everything else is re-derived from
durable state (Phase 7B.7 Part 4/6). `reconstruct_launch_request` is that
deterministic mapping, pure and side-effect-free: no session, no
repository, no authorization logic, no Docker, no Celery. It trusts
nothing beyond what is already on the row -- if the row's
`capability`/`operation`/`resource_class` are inconsistent, `LaunchRequest`
still constructs (that combination is only ever a real problem for
`build_candidate()`/`validate_and_approve()` to reject); this function's
only job is the field mapping, not validation `docker_policy.py` already
owns.

`prepare_approved_launch` (Phase 7B.10, revised 7B.11, revised 7B.14) is
the orchestration layer immediately above Docker: `job_id -> atomic
PENDING claim -> VALIDATING -> reconstruct_launch_request() ->
build_candidate() -> validate_and_approve() -> ApprovedLaunchSpec ->
create ExecutionAttempt(PENDING_CREATE) -> commit -> ApprovedLaunchPreparation`.
It launches nothing -- no Docker, no Celery task, no subprocess.

Phase 7B.11 replaces 7B.10's read-only `status == PENDING` check (a
read-then-write gap: two concurrent callers could both observe `PENDING`
and both proceed) with `ExecutionJobRepository.claim_pending_job()`, an
atomic conditional `UPDATE ... WHERE status = 'PENDING'`. Only the winner
of that race reaches the guard pipeline at all -- see that method's
docstring for why the update itself, not any code here, is what makes
this safe under concurrency.

Phase 7B.14 adds `ExecutionAttempt` creation -- deliberately AFTER
`validate_and_approve()` succeeds (Option B of the two orderings Phase
7B.14 considered), not before: an attempt represents an actual launchable
execution, not merely an eligibility-validation attempt that never passed
the guard. `attempt_number` is hardcoded to `1`, not computed via
`max(attempt_number) + 1` or any allocator -- this is provably correct
under the CURRENT architecture, not a shortcut: `claim_pending_job()`
guarantees this code path is reachable AT MOST ONCE per job (no retry or
reconciliation path exists yet that could ever re-claim an
already-attempted job), so "this job already has an attempt" is not a
reachable case here. `attempt.id` is generated in Python (`uuid.uuid4()`)
BEFORE the `ExecutionAttempt` is constructed, specifically so
`container_name_for_attempt()` has a real id to derive the deterministic
name from before the row is ever inserted -- `BaseModel.id`'s
`default=uuid.uuid4` is a flush-time default and would not exist yet if
left to fire on its own.

Failure policy (deliberately the smallest one, not a state machine): once
claimed, a job stays `VALIDATING` regardless of what happens next in this
function -- a guard/resolver rejection, OR an attempt-creation failure
(e.g. `IntegrityError`), is NOT reverted back to `PENDING` (that would let
a `SecurityBlocked` result loop into an automatic retry, which must never
happen) and is NOT advanced to `FAILED` either (this slice does not
invent that transition). Both propagate unchanged -- this layer neither
catches nor translates them. The claim (Phase 7B.11) and the attempt
creation (Phase 7B.14) are TWO SEPARATE COMMITTED TRANSACTIONS: the claim
commits immediately and unconditionally inside `claim_pending_job()`; the
attempt is only added/flushed (never committed) until this function's own
`await session.commit()`, which runs only after `create()` succeeds. If
`create()` itself raises (e.g. a constraint violation), nothing was ever
committed for the attempt -- no partial row survives at the database
level, Postgres's own transactional guarantee, not anything this code
adds. A crash between claim and attempt-commit, a guard rejection, or an
attempt-creation failure all leave the row parked at `VALIDATING` for a
future reconciliation mechanism (the same accepted, documented pattern
`app.workers.reconciliation.reconcile_stale_research_runs` already uses
for `ResearchRun` rows stuck at `RUNNING`) -- not implemented in this
slice.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.execution.enums import ExecutionJobStatus
from app.modules.execution.models import ExecutionAttempt, ExecutionJob
from app.modules.execution.repository import ExecutionAttemptRepository, ExecutionJobRepository
from execution_launcher.docker_policy import validate_and_approve
from execution_launcher.models import (
    ApprovedLaunchSpec,
    InputResolutionError,
    LaunchRequest,
    SecurityBlocked,
)
from execution_launcher.resolvers import ProductionInputResolver
from execution_launcher.translator import build_candidate

#: Persisted on a LAUNCHING job when a retry-recovery attempt's guard
#: pipeline rejects it (Sprint 16 Phase 7B.19 design, 7B.21
#: implementation). Fixed and complete -- no interpolation -- matching
#: `reconciliation.py`'s existing diagnostic constants. A guard
#: rejection here is a TERMINAL state for automatic recovery: the job
#: stays LAUNCHING, nothing retries this job again automatically
#: (Phase 7B.20's single-retry boundary), and clearing it requires an
#: operator to look at why the guard rejected the retry.
STALE_LAUNCHING_JOB_DIAGNOSTIC = (
    "Execution job's retry allocation could not be recovered automatically: "
    "guard validation rejected the retry."
)


class ExecutionJobNotFoundError(Exception):
    """Raised when the referenced `ExecutionJob` does not exist -- also
    reused by `get_owned_job` (Sprint 16 Phase 7B.23) when a job exists
    but is not owned by the caller, so "not yours" and "does not exist"
    are indistinguishable from the outside, matching
    `ExperimentPlanNotFoundError`'s established pattern."""

    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id
        super().__init__(f"execution job {job_id} does not exist")


async def get_owned_job(owner_id: uuid.UUID, job_id: uuid.UUID, session: AsyncSession) -> ExecutionJob:
    """Fetch a job, raising `ExecutionJobNotFoundError` unless it exists
    AND is owned by `owner_id` (Sprint 16 Phase 7B.23) -- backs
    `GET /execution/jobs/{job_id}`. Checked directly against `job.owner_id`
    rather than via a `Project` join: `owner_id` is captured on the job at
    creation time from the same project-ownership check
    `ExperimentPlanService._ensure_project_owned` already performed, so
    this achieves the same "ownership enforced transitively through the
    project" guarantee every other module follows, without a redundant
    join here.
    """
    job = await ExecutionJobRepository(session).get_by_id(job_id)
    if job is None or job.owner_id != owner_id:
        raise ExecutionJobNotFoundError(job_id)
    return job


async def list_owned_jobs(owner_id: uuid.UUID, session: AsyncSession) -> list[ExecutionJob]:
    """Every job owned by `owner_id` (Sprint 16 Phase 7B.23) -- backs
    `GET /execution/jobs`."""
    return await ExecutionJobRepository(session).list_by_owner(owner_id)


async def request_execution_cancellation(
    owner_id: uuid.UUID, job_id: uuid.UUID, session: AsyncSession
) -> ExecutionJob | None:
    """The smallest possible cancellation entry point (Sprint 16 Phase
    7B.28) -- ownership-checked (matching `get_owned_job`'s "not yours"
    == "does not exist" precedent), then a thin pass-through to the
    repository's atomic `RUNNING -> CANCEL_REQUESTED` claim. No new
    task, queue, or router route; no generalized cancellation framework
    -- callers (tests today, a future router route if one is ever
    added) call this directly.

    Raises `ExecutionJobNotFoundError` if the job does not exist or is
    not owned by `owner_id` (matching `get_owned_job`'s own "not yours"
    == "does not exist" precedent). Returns `None` (not an error) if the
    job exists and is owned but was not `RUNNING` at the moment of the
    attempt -- already terminal, or a concurrent caller won first -- the
    actual container termination happens later, asynchronously, inside
    `execution_launcher.launcher.execute_approved_launch`'s own polling
    loop, which observes this durable request; this function only makes
    the REQUEST durable, exactly as scoped ("cancellation request
    becomes durable" is step 1 of 7, not the whole sequence).
    """
    job = await get_owned_job(owner_id, job_id, session)
    return await ExecutionJobRepository(session).request_cancellation(job.id)


class ExecutionJobNotEligibleError(Exception):
    """Raised when `claim_pending_job` could not claim the job -- either it
    was never `PENDING`, or a concurrent caller won the race first (Phase
    7B.7 Part 10/12's idempotency concern: a redelivered Celery message,
    or a genuine duplicate launcher attempt, must not silently re-launch a
    job someone else already claimed). `status` reflects a best-effort
    follow-up read taken after the failed claim, for diagnostics only --
    it is not used to decide anything and may itself be stale by the time
    it is read."""

    def __init__(self, job_id: uuid.UUID, status: ExecutionJobStatus) -> None:
        self.job_id = job_id
        self.status = status
        super().__init__(f"execution job {job_id} is not eligible to launch (status={status.value})")


class ExecutionRetryClaimSupersededError(Exception):
    """Raised by `prepare_retry_attempt` when its own claim (won moments
    earlier) is no longer current by the time it tries to materialize --
    a concurrent `recover_interrupted_retry_attempt` won the row lock
    first and already materialized (or is materializing) attempt N. Not
    a bug and not retried automatically: the retry this caller was
    authorized to make has already been made by someone else."""

    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id
        super().__init__(f"execution job {job_id}'s retry claim was superseded before materialization")


def container_name_for_attempt(attempt_id: uuid.UUID) -> str:
    """The deterministic Docker container name for one attempt (Phase
    7B.12 Part 5) -- a pure function of `attempt_id` alone.

    Deterministic: the same `attempt_id` always yields the same string.
    No randomness beyond `attempt_id`'s own prior generation, no
    timestamp, no project/user name, no secret. `"aikdap-exec-" + str(uuid)`
    is 48 characters -- well inside both the 255-char database column and
    Docker's own container-name length limit -- and uses only characters
    Docker accepts in a name (`[a-zA-Z0-9][a-zA-Z0-9_.-]+`): a hyphenated
    lowercase UUID satisfies that with no extra sanitization needed. Never
    calls Docker, never imports the Docker SDK -- storage-layer identity
    computation only.
    """
    return f"aikdap-exec-{attempt_id}"


@dataclass(frozen=True)
class ApprovedLaunchPreparation:
    """What `prepare_approved_launch` returns once a launch has passed the
    full guard pipeline AND been durably assigned an attempt identity.

    Carries Docker IDENTITY for a future launcher to use (`attempt_id`,
    `container_name`) -- never Docker POLICY, which stays entirely inside
    `approved_spec` (produced, unmodified, by `validate_and_approve()`).
    Deliberately has no field for image/network/mounts/command/privileged/
    env/capabilities -- adding one here would duplicate what
    `ApprovedLaunchSpec` already owns and give a future launcher two
    places to read policy from instead of one.
    """

    approved_spec: ApprovedLaunchSpec
    attempt_id: uuid.UUID
    container_name: str


def reconstruct_launch_request(job: ExecutionJob) -> LaunchRequest:
    """Maps a persisted `ExecutionJob` row back to the exact `LaunchRequest`
    shape `build_candidate()`/`validate_and_approve()` already consume --
    no adapter, no duplicate mapping layer anywhere else."""
    return LaunchRequest(
        job_id=job.id,
        experiment_plan_id=job.experiment_plan_id,
        experiment_plan_version=job.experiment_plan_version,
        owner_id=job.owner_id,
        project_id=job.project_id,
        capability=job.capability,
        operation=job.operation,
        parameters=job.parameters,
        resource_class=job.resource_class,
        input_asset_ids=[uuid.UUID(asset_id) for asset_id in job.input_asset_ids],
    )


async def prepare_approved_launch(job_id: uuid.UUID, session: AsyncSession) -> ApprovedLaunchPreparation:
    """Atomically claims a durable `ExecutionJob`, reconstructs its
    `LaunchRequest`, runs it through the existing async candidate/guard
    pipeline, and -- only once that succeeds -- durably creates the
    `ExecutionAttempt` a future Docker launcher will use. Returns an
    `ApprovedLaunchPreparation` (the approved spec plus the new attempt's
    identity) for that future boundary to consume.

    The claim attempt runs first, as a single atomic operation, before any
    "does this job exist" read -- so a caller that loses the claim race
    never observes stale pre-race state (see module docstring). Only on a
    failed claim do we read the row again, purely to produce an accurate
    exception: `None` means the job never existed
    (`ExecutionJobNotFoundError`); a real row means it was not `PENDING`
    at claim time, whether because it never was or because a concurrent
    caller won first (`ExecutionJobNotEligibleError`). A caller that loses
    the claim race never reaches attempt creation at all -- the
    concurrency safety this function inherits for attempt creation comes
    entirely from `claim_pending_job()` already being exclusive, not from
    anything added here.

    `SecurityBlocked`/`InputResolutionError` from the guard pipeline, and
    any exception `ExecutionAttemptRepository.create()` raises (e.g. an
    `IntegrityError`), all propagate unchanged -- this layer neither
    catches nor translates them, matching Phase 7B.9's boundary: validation
    is the guard's job, not this orchestration step's. See the module
    docstring for what happens to the job's status in either case.
    """
    repository = ExecutionJobRepository(session)
    claimed = await repository.claim_pending_job(job_id)
    if claimed is None:
        job = await repository.get_by_id(job_id)
        if job is None:
            raise ExecutionJobNotFoundError(job_id)
        raise ExecutionJobNotEligibleError(job_id, job.status)

    request = reconstruct_launch_request(claimed)
    resolver = ProductionInputResolver(session)
    candidate = await build_candidate(request, resolver)
    approved = await validate_and_approve(candidate, resolver)

    attempt_id = uuid.uuid4()
    name = container_name_for_attempt(attempt_id)
    attempt = ExecutionAttempt(
        id=attempt_id,
        execution_job_id=claimed.id,
        attempt_number=1,
        container_name=name,
    )
    await ExecutionAttemptRepository(session).create(attempt)
    await session.commit()

    return ApprovedLaunchPreparation(approved_spec=approved, attempt_id=attempt_id, container_name=name)


async def _next_attempt_number(job_id: uuid.UUID, session: AsyncSession) -> int:
    """`COALESCE(MAX(attempt_number), 0) + 1` for `job_id`. Safe ONLY when
    called by a caller that already holds an exclusive lock on the
    corresponding `ExecutionJob` row for the duration of this call and
    the subsequent `INSERT` -- this function enforces nothing itself
    (Sprint 16 Phase 7B.20 Q6/7B.21 GIVEN 1). Both call sites below
    satisfy that precondition: `prepare_retry_attempt` via `SELECT ...
    FOR UPDATE`, `recover_interrupted_retry_attempt` via the self-loop
    `UPDATE`'s own implicit row lock.
    """
    result = await session.execute(
        select(func.coalesce(func.max(ExecutionAttempt.attempt_number), 0) + 1).where(
            ExecutionAttempt.execution_job_id == job_id
        )
    )
    return result.scalar_one()


async def prepare_retry_attempt(job_id: uuid.UUID, session: AsyncSession) -> ApprovedLaunchPreparation:
    """The ORIGINAL retry materializer (Sprint 16 Phase 7B.18 design,
    amended per 7B.20/7B.21 with the `FOR UPDATE` + epoch-freshness
    re-check). Claims a stale `VALIDATING` job (`VALIDATING ->
    LAUNCHING`, durable, committed immediately by
    `claim_stale_validating_job_for_retry` -- same contract as
    `claim_pending_job`), re-runs the FULL guard pipeline (unlocked, may
    take real I/O time), then materializes the next attempt under an
    exclusive row lock with an epoch-freshness re-check -- so a
    concurrent `recover_interrupted_retry_attempt`, racing this same job
    because this claim looked abandoned, can never produce a second
    attempt alongside this one.

    Two transactions, deliberately, matching `prepare_approved_launch`'s
    existing shape: the claim commits on its own; guard pipeline work
    happens with NO lock held (holding a row lock across unbounded async
    I/O is the exact pattern Phase 7B.20 rejected); materialization is a
    THIRD, final, short transaction -- lock, re-check, allocate, insert,
    commit, all together.

    Raises `ExecutionRetryClaimSupersededError` if, by the time this
    reaches materialization, `updated_at` no longer matches the epoch
    this call's own claim established -- meaning a recovery worker
    already took over. This is an expected, not-retried outcome, not a
    bug: the retry this call was authorized to make has already been
    made by someone else.
    """
    repository = ExecutionJobRepository(session)
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.execution_job_validating_stale_after_seconds
    )
    claimed = await repository.claim_stale_validating_job_for_retry(job_id, cutoff)
    if claimed is None:
        job = await repository.get_by_id(job_id)
        if job is None:
            raise ExecutionJobNotFoundError(job_id)
        raise ExecutionJobNotEligibleError(job_id, job.status)

    my_epoch = claimed.updated_at

    request = reconstruct_launch_request(claimed)
    resolver = ProductionInputResolver(session)
    candidate = await build_candidate(request, resolver)
    approved = await validate_and_approve(candidate, resolver)

    locked_result = await session.execute(
        select(ExecutionJob).where(ExecutionJob.id == job_id).with_for_update()
    )
    current = locked_result.scalar_one()
    if current.updated_at != my_epoch:
        raise ExecutionRetryClaimSupersededError(job_id)

    next_number = await _next_attempt_number(job_id, session)

    attempt_id = uuid.uuid4()
    name = container_name_for_attempt(attempt_id)
    attempt = ExecutionAttempt(
        id=attempt_id,
        execution_job_id=job_id,
        attempt_number=next_number,
        container_name=name,
    )
    await ExecutionAttemptRepository(session).create(attempt)
    await session.commit()

    return ApprovedLaunchPreparation(approved_spec=approved, attempt_id=attempt_id, container_name=name)


async def recover_interrupted_retry_attempt(
    job_id: uuid.UUID, session: AsyncSession
) -> ApprovedLaunchPreparation | None:
    """The recovery materializer (Sprint 16 Phase 7B.19/7B.20 design,
    implemented 7B.21). Assumes the caller (reconciliation detection)
    has already determined `job_id` is a `LAUNCHING`, stale job worth
    attempting recovery for -- this function re-verifies the only fact
    that actually matters (no attempt has materialized yet) atomically,
    itself.

    Re-runs the FULL guard pipeline first, with NO lock held (identical
    reasoning to `prepare_retry_attempt`: a stale guard result can only
    waste this call's own work, never cause a duplicate attempt, because
    nothing is claimed yet at this point). If guards REJECT
    (`SecurityBlocked`/`InputResolutionError`), records the fixed
    `STALE_LAUNCHING_JOB_DIAGNOSTIC` on `job.reason` (idempotent -- skips
    the write if already set) and re-raises unchanged: this is a
    terminal state for automatic recovery, requiring operator action,
    not a transition this function invents.

    If guards pass, attempts the fused claim: `ExecutionJobRepository.
    _claim_launching_for_recovery` (flush only, holds the row lock),
    immediately followed -- same transaction -- by attempt-number
    allocation and `INSERT`, then this function's own single `commit()`.
    Returns `None` if the claim matched 0 rows: NOT an error, just "lost
    the race" -- another worker already materialized (or is
    materializing) the retry since this call last looked, or a
    concurrent `prepare_retry_attempt`/other recovery attempt won first.
    """
    job_repository = ExecutionJobRepository(session)
    job = await job_repository.get_by_id(job_id)
    if job is None:
        raise ExecutionJobNotFoundError(job_id)
    if job.status is not ExecutionJobStatus.LAUNCHING:
        raise ExecutionJobNotEligibleError(job_id, job.status)

    request = reconstruct_launch_request(job)
    resolver = ProductionInputResolver(session)
    try:
        candidate = await build_candidate(request, resolver)
        approved = await validate_and_approve(candidate, resolver)
    except (SecurityBlocked, InputResolutionError):
        if job.reason != STALE_LAUNCHING_JOB_DIAGNOSTIC:
            job.reason = STALE_LAUNCHING_JOB_DIAGNOSTIC
            await session.commit()
        raise

    claimed = await job_repository._claim_launching_for_recovery(job_id)  # noqa: SLF001 -- intentional, same-module escape hatch
    if claimed is None:
        return None

    next_number = await _next_attempt_number(job_id, session)

    attempt_id = uuid.uuid4()
    name = container_name_for_attempt(attempt_id)
    attempt = ExecutionAttempt(
        id=attempt_id,
        execution_job_id=job_id,
        attempt_number=next_number,
        container_name=name,
    )
    await ExecutionAttemptRepository(session).create(attempt)
    await session.commit()

    return ApprovedLaunchPreparation(approved_spec=approved, attempt_id=attempt_id, container_name=name)
