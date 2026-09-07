"""Sprint 16 Phase 7B.21 -- retry-recovery concurrency proofs.

Phase 7B.20 designed a protocol proving (on paper) that a job whose
retry-allocation claim (`VALIDATING -> LAUNCHING`) commits but then
crashes before `ExecutionAttempt` creation can still be recovered by a
later worker, exactly once, with no possibility of a duplicate
`attempt_number` even when the original claimant is genuinely still
alive and racing a recovery attempt. This file is the proof: every test
here drives REAL concurrent `AsyncSession`s against REAL Postgres, with
explicit ordering control where the property under test depends on
which transaction observes which committed state -- not on
`asyncio.gather` scheduling luck.

Two materialization code paths are exercised:
  - `service.recover_interrupted_retry_attempt` -- the self-loop
    (`LAUNCHING -> LAUNCHING`) recovery claim, flush-only, fused with
    attempt-number allocation and INSERT in one caller-owned
    transaction (Phase 7B.21 GIVEN 1).
  - The ORIGINAL retry materializer's tail (`SELECT ... FOR UPDATE` +
    epoch re-check + allocate + insert), replicated in T2 via the
    exact same repository/service primitives `prepare_retry_attempt`
    itself uses (`_next_attempt_number`), not reimplemented separately
    -- so T2 tests the real mechanism, not a stand-in for it.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.session import async_session_factory, engine
from app.modules.assets.enums import AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.auth.models import User
from app.modules.execution.enums import ExecutionJobStatus
from app.modules.execution.models import ExecutionAttempt, ExecutionJob
from app.modules.execution.repository import ExecutionAttemptRepository, ExecutionJobRepository
from app.modules.execution.service import (
    ApprovedLaunchPreparation,
    _next_attempt_number,
    container_name_for_attempt,
    recover_interrupted_retry_attempt,
)
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from execution_launcher.models import ExecutionCapability, ExecutionOperation, ResourceClass


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_between_tests():
    await engine.dispose()
    yield


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-retryrecovery-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Retry Recovery Concurrency Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_retry_recovery_concurrency.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Retry Recovery Concurrency Test Project")
    yield proj
    user = await session.get(User, proj.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


async def _write_real_file(project: Project, *, filename: str) -> str:
    storage = get_storage_provider()
    return await storage.save(project_id=project.id, filename=filename, content=b"1,2\n3,4\n")


async def _make_asset(session, project: Project, *, storage_path: str, file_name: str) -> Asset:
    asset = Asset(
        project_id=project.id,
        owner_id=project.owner_id,
        title=file_name,
        file_name=file_name,
        file_extension=file_name.rsplit(".", 1)[-1],
        mime_type="text/csv",
        file_size=0,
        storage_path=storage_path,
        checksum="test-checksum",
        asset_type=AssetType.DATASET,
        status=AssetStatus.ACTIVE,
        source=AssetSource.UPLOAD,
        tags=[],
    )
    return await AssetRepository(session).create(asset)


async def _resolvable_asset(session, project: Project, *, filename: str) -> Asset:
    storage_path = await _write_real_file(project, filename=filename)
    asset = await _make_asset(session, project, storage_path=storage_path, file_name=filename)
    await session.commit()
    return asset


async def _make_launching_job(
    session,
    project: Project,
    *,
    input_asset_ids: list[uuid.UUID],
    with_first_attempt: bool = True,
) -> ExecutionJob:
    """Directly constructs a job already at `LAUNCHING`, optionally with
    a pre-existing "attempt 1" (representing the original launch) --
    matching `test_execution_job_reconciliation.py`'s established
    direct-status-construction pattern. `recover_interrupted_retry_attempt`
    only cares about CURRENT status and attempt existence, not how the
    job arrived at `LAUNCHING`, so this is a faithful, simpler setup
    than driving the real claim flow first.

    Attempt 1's `created_at` and the job's `updated_at` are given
    EXPLICIT, deliberately-separated timestamps rather than left to
    `server_default=func.now()`. In the real flow these always differ
    by real wall-clock time (attempt 1 is created by
    `prepare_approved_launch` at the original launch; the job's
    `updated_at` is bumped again, much later, by the retry claim) -- but
    naively constructing both within the SAME uncommitted transaction
    would give them the SAME Postgres `now()` (constant per transaction,
    confirmed empirically this phase), making attempt 1's `created_at`
    equal to the job's `updated_at` -- which `_claim_launching_for_recovery`'s
    `created_at >= updated_at` check would then (correctly, given that
    input) treat as "this epoch already materialized". Explicit
    timestamps avoid manufacturing a scenario the real system cannot
    produce.
    """
    now = datetime.now(timezone.utc)
    first_attempt_created_at = now - timedelta(seconds=60)
    job_claim_epoch = now

    job = ExecutionJob(
        project_id=project.id,
        owner_id=project.owner_id,
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        capability=ExecutionCapability.ARRAY_COMPUTE,
        operation=ExecutionOperation.MATMUL,
        resource_class=ResourceClass.CLASS_ARRAY,
        parameters={},
        input_asset_ids=[str(a) for a in input_asset_ids],
        status=ExecutionJobStatus.LAUNCHING,
        updated_at=job_claim_epoch,
    )
    session.add(job)
    await session.flush()
    if with_first_attempt:
        first = ExecutionAttempt(
            execution_job_id=job.id,
            attempt_number=1,
            container_name=container_name_for_attempt(uuid.uuid4()),
            created_at=first_attempt_created_at,
        )
        session.add(first)
        await session.flush()
    await session.commit()
    await session.refresh(job)
    return job


async def _attempts_for_job(job_id: uuid.UUID) -> list[ExecutionAttempt]:
    async with async_session_factory() as verify_session:
        result = await verify_session.execute(
            select(ExecutionAttempt).where(ExecutionAttempt.execution_job_id == job_id).order_by(
                ExecutionAttempt.attempt_number
            )
        )
        return list(result.scalars().all())


async def _reload_job(job_id: uuid.UUID) -> ExecutionJob:
    async with async_session_factory() as verify_session:
        job = await verify_session.get(ExecutionJob, job_id)
        assert job is not None
        return job


# ---------------------------------------------------------------------------
# T1 -- two recovery workers, same stale job -> exactly one attempt.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t1_two_recovery_workers_same_job_exactly_one_attempt(session, project):
    asset = await _resolvable_asset(session, project, filename="t1.csv")
    job = await _make_launching_job(session, project, input_asset_ids=[asset.id])

    async def _recover() -> ApprovedLaunchPreparation | None:
        async with async_session_factory() as worker_session:
            return await recover_interrupted_retry_attempt(job.id, worker_session)

    result_a, result_b = await asyncio.gather(_recover(), _recover())

    successes = [r for r in (result_a, result_b) if r is not None]
    losses = [r for r in (result_a, result_b) if r is None]
    assert len(successes) == 1, f"expected exactly 1 success, got {len(successes)}"
    assert len(losses) == 1

    attempts = await _attempts_for_job(job.id)
    assert [a.attempt_number for a in attempts] == [1, 2]
    assert attempts[1].id == successes[0].attempt_id
    assert attempts[1].container_name == successes[0].container_name


# ---------------------------------------------------------------------------
# T2 -- original claimant vs recovery worker -> exactly one attempt.
#
# "Worker A" (the original claimant, already holding a won
# VALIDATING->LAUNCHING claim from earlier) is driven through the exact
# same tail `prepare_retry_attempt` uses -- FOR UPDATE, epoch re-check,
# `_next_attempt_number`, INSERT -- via the real production primitives,
# not a reimplementation, so this proves the real mechanism.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t2_original_claimant_vs_recovery_worker_exactly_one_attempt(session, project):
    asset = await _resolvable_asset(session, project, filename="t2.csv")
    job = await _make_launching_job(session, project, input_asset_ids=[asset.id])
    my_epoch = job.updated_at  # what worker A's earlier (already-won) claim observed

    async def _worker_a_materialize() -> ApprovedLaunchPreparation | None:
        async with async_session_factory() as a_session:
            locked = await a_session.execute(
                select(ExecutionJob).where(ExecutionJob.id == job.id).with_for_update()
            )
            current = locked.scalar_one()
            if current.updated_at != my_epoch:
                return None  # superseded -- recovery won first
            next_number = await _next_attempt_number(job.id, a_session)
            attempt_id = uuid.uuid4()
            name = container_name_for_attempt(attempt_id)
            attempt = ExecutionAttempt(
                id=attempt_id, execution_job_id=job.id, attempt_number=next_number, container_name=name
            )
            await ExecutionAttemptRepository(a_session).create(attempt)
            await a_session.commit()
            return ApprovedLaunchPreparation(approved_spec=None, attempt_id=attempt_id, container_name=name)  # type: ignore[arg-type]

    async def _worker_b_recover() -> ApprovedLaunchPreparation | None:
        async with async_session_factory() as b_session:
            return await recover_interrupted_retry_attempt(job.id, b_session)

    result_a, result_b = await asyncio.gather(_worker_a_materialize(), _worker_b_recover())

    successes = [r for r in (result_a, result_b) if r is not None]
    assert len(successes) == 1, f"expected exactly 1 success, got {len(successes)}: A={result_a} B={result_b}"

    attempts = await _attempts_for_job(job.id)
    assert [a.attempt_number for a in attempts] == [1, 2], "no third attempt allocated, no gap"


# ---------------------------------------------------------------------------
# T3 -- recovery worker crashes after claim, before insert (rollback) ->
# a later recovery worker still succeeds. Deterministic: the "crash" is
# an explicit rollback, not a timing simulation.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t3_crash_after_claim_before_insert_then_later_recovery_succeeds(session, project):
    asset = await _resolvable_asset(session, project, filename="t3.csv")
    job = await _make_launching_job(session, project, input_asset_ids=[asset.id])
    before_updated_at = job.updated_at

    async with async_session_factory() as crashing_session:
        claimed = await ExecutionJobRepository(crashing_session)._claim_launching_for_recovery(job.id)
        assert claimed is not None, "claim must succeed before the simulated crash"
        # Simulated crash: never commit. Rollback discards the flushed
        # UPDATE entirely -- the real-world equivalent of the process
        # dying before COMMIT.
        await crashing_session.rollback()

    reloaded = await _reload_job(job.id)
    assert reloaded.status is ExecutionJobStatus.LAUNCHING
    assert reloaded.updated_at == before_updated_at, "the crash must leave zero durable trace"
    assert [a.attempt_number for a in await _attempts_for_job(job.id)] == [1], "no attempt from the crashed claim"

    async with async_session_factory() as later_session:
        preparation = await recover_interrupted_retry_attempt(job.id, later_session)

    assert preparation is not None, "a later recovery worker must still be able to recover"
    attempts = await _attempts_for_job(job.id)
    assert [a.attempt_number for a in attempts] == [1, 2]
    assert attempts[1].id == preparation.attempt_id


# ---------------------------------------------------------------------------
# T4 -- recovery after an attempt already exists -> no write, returns None.
# Purely sequential; no concurrency needed to prove this.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t4_recovery_after_attempt_already_materialized_is_a_no_op(session, project):
    asset = await _resolvable_asset(session, project, filename="t4.csv")
    job = await _make_launching_job(session, project, input_asset_ids=[asset.id])
    epoch_before = job.updated_at

    # Simulate "materialization already completed": an attempt exists
    # with created_at >= job.updated_at.
    second_attempt = ExecutionAttempt(
        execution_job_id=job.id,
        attempt_number=2,
        container_name=container_name_for_attempt(uuid.uuid4()),
    )
    session.add(second_attempt)
    await session.flush()
    await session.commit()

    async with async_session_factory() as worker_session:
        result = await recover_interrupted_retry_attempt(job.id, worker_session)

    assert result is None

    reloaded = await _reload_job(job.id)
    assert reloaded.updated_at == epoch_before, "self-loop UPDATE must not have matched, so no bump"

    attempts = await _attempts_for_job(job.id)
    assert [a.attempt_number for a in attempts] == [1, 2], "still exactly the pre-existing two, nothing new"


# ---------------------------------------------------------------------------
# T5 -- loser blocks on the row lock, then observes 0 matched rows.
# Explicit asyncio.Event ordering: B is guaranteed to issue its claim
# WHILE A's transaction is open and uncommitted, so B's own await
# genuinely blocks on Postgres's row lock rather than merely losing a
# race that could have gone either way.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t5_loser_blocks_then_observes_zero_matched_rows(session, project):
    asset = await _resolvable_asset(session, project, filename="t5.csv")
    job = await _make_launching_job(session, project, input_asset_ids=[asset.id])

    a_holds_lock = asyncio.Event()
    a_may_finish = asyncio.Event()
    hold_seconds = 0.4

    async def _worker_a() -> ApprovedLaunchPreparation | None:
        async with async_session_factory() as a_session:
            claimed = await ExecutionJobRepository(a_session)._claim_launching_for_recovery(job.id)
            assert claimed is not None
            a_holds_lock.set()  # signal B: A's UPDATE has run, uncommitted, lock held
            await asyncio.wait_for(a_may_finish.wait(), timeout=5)
            next_number = await _next_attempt_number(job.id, a_session)
            attempt_id = uuid.uuid4()
            name = container_name_for_attempt(attempt_id)
            attempt = ExecutionAttempt(
                id=attempt_id, execution_job_id=job.id, attempt_number=next_number, container_name=name
            )
            await ExecutionAttemptRepository(a_session).create(attempt)
            await a_session.commit()
            return ApprovedLaunchPreparation(approved_spec=None, attempt_id=attempt_id, container_name=name)  # type: ignore[arg-type]

    async def _worker_b() -> tuple[ExecutionJob | None, float]:
        await asyncio.wait_for(a_holds_lock.wait(), timeout=5)
        # A is now holding the row lock, uncommitted. Give A a head
        # start inside its own critical section before B's UPDATE is
        # even issued, then let A finish shortly after B blocks --
        # proving B's wait time tracks A's hold time, not zero.
        await asyncio.sleep(0.05)
        started = time.monotonic()

        async def _release_a_soon() -> None:
            await asyncio.sleep(hold_seconds)
            a_may_finish.set()

        release_task = asyncio.create_task(_release_a_soon())
        async with async_session_factory() as b_session:
            claimed = await ExecutionJobRepository(b_session)._claim_launching_for_recovery(job.id)
            await b_session.rollback()
        elapsed = time.monotonic() - started
        await release_task
        return claimed, elapsed

    (result_a, (result_b, b_elapsed)) = await asyncio.gather(_worker_a(), _worker_b())

    assert result_a is not None, "A must win (B is deliberately delayed until A holds the lock)"
    assert result_b is None, "B must observe 0 matched rows once unblocked"
    # B's UPDATE call could only return after being blocked on A's row
    # lock for roughly A's hold duration -- a fast (non-blocking) return
    # would mean B never actually contended for the lock at all.
    assert b_elapsed >= hold_seconds * 0.6, (
        f"B returned in {b_elapsed:.3f}s, too fast to have genuinely blocked on A's "
        f"{hold_seconds}s-held row lock -- this would mean the test failed to force "
        f"the intended interleaving, not that the invariant is unsafe"
    )

    attempts = await _attempts_for_job(job.id)
    assert [a.attempt_number for a in attempts] == [1, 2]


# ---------------------------------------------------------------------------
# T6 -- attempt_number is never double-allocated across any interleaving.
# N-way concurrent recovery attempts against the same job.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t6_attempt_number_never_double_allocated_n_way(session, project):
    asset = await _resolvable_asset(session, project, filename="t6.csv")
    job = await _make_launching_job(session, project, input_asset_ids=[asset.id])

    concurrency = 6

    async def _recover() -> ApprovedLaunchPreparation | None:
        async with async_session_factory() as worker_session:
            return await recover_interrupted_retry_attempt(job.id, worker_session)

    results = await asyncio.gather(*[_recover() for _ in range(concurrency)])

    successes = [r for r in results if r is not None]
    losses = [r for r in results if r is None]
    assert len(successes) == 1, f"expected exactly 1 success out of {concurrency}, got {len(successes)}"
    assert len(losses) == concurrency - 1

    attempts = await _attempts_for_job(job.id)
    numbers = [a.attempt_number for a in attempts]
    assert numbers == [1, 2], f"expected exactly [1, 2], got {numbers} -- any extra number is a duplicate allocation"
    assert len(set(numbers)) == len(numbers), "no duplicate attempt_number values"


# ---------------------------------------------------------------------------
# Structural: composite unique constraint still rejects a same-number
# collision even if the claim logic were ever bypassed -- defense in
# depth, re-verified live rather than assumed carried over from 7B.14.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_unique_constraint_still_rejects_manual_duplicate(session, project):
    asset = await _resolvable_asset(session, project, filename="constraint.csv")
    job = await _make_launching_job(session, project, input_asset_ids=[asset.id])

    async with async_session_factory() as violating_session:
        duplicate = ExecutionAttempt(
            execution_job_id=job.id,
            attempt_number=1,  # collides with the pre-existing "attempt 1"
            container_name=container_name_for_attempt(uuid.uuid4()),
        )
        violating_session.add(duplicate)
        with pytest.raises(IntegrityError):
            await violating_session.flush()
