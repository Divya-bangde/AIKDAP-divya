"""Sprint 16 Phase 7B.16 -- stale `ExecutionJob` `VALIDATING` reconciliation.

Root problem: `ExecutionJobRepository.claim_pending_job()` moves a job
`PENDING -> VALIDATING` and commits immediately. Phase 7B.10's documented
failure policy then leaves the job parked at `VALIDATING` forever on a
guard/resolver rejection, an attempt-creation failure, or a crash
anywhere in `prepare_approved_launch()`. Nothing ever revisited those
rows -- the same orphan class Sprint 9J found for `ResearchRun` and
Phase 7B.15 found for `ExecutionAttempt`, one level up.

`reconcile_stale_validating_execution_jobs()` is the job-level mirror of
Phase 7B.15's attempt-level reconciler: detect, record a bounded fixed
diagnostic, change nothing else. These tests exist as much to pin down
what it refuses to do (no status change, no retry, no attempt-table
inspection to infer Docker state) as what it does.

Run against the REAL Postgres test database (see `conftest.py`), never
SQLite: the property under test -- that `claim_pending_job()`'s bulk
`UPDATE` genuinely bumps `updated_at`, and that this reconciler's own
write does too -- is exact real-database timestamp behavior a mock
would paper over.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.core.config import settings
from app.database.session import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.execution.enums import ExecutionAttemptStatus, ExecutionJobStatus
from app.modules.execution.models import ExecutionAttempt, ExecutionJob
from app.modules.execution.repository import ExecutionJobRepository
from app.modules.execution.service import container_name_for_attempt
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.workers.reconciliation import (
    STALE_VALIDATING_JOB_DIAGNOSTIC,
    reconcile_stale_validating_execution_jobs,
)
from execution_launcher.models import ExecutionCapability, ExecutionOperation, ResourceClass


@pytest_asyncio.fixture(autouse=True)
async def _isolated_engine_and_clean_baseline():
    """Same two concerns as `test_execution_attempt_reconciliation.py`'s
    equivalent fixture, deliberately kept together.

    `engine.dispose()` is the same narrow, test-local workaround every
    `test_execution_*` file uses for the repository's known
    module-level-engine + function-scoped-event-loop interaction. Does
    not touch `app/database/session.py`, `conftest.py`, or `pytest.ini`.

    Reconciling once up front gives every test a known-clean baseline
    against real, possibly ambient, stale `VALIDATING` jobs -- an
    ordinary (idempotent) use of the function under test, not a
    workaround for it.
    """
    await engine.dispose()
    await reconcile_stale_validating_execution_jobs()
    yield


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-jobrecon-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Job Reconciliation Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_job_reconciliation.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Job Reconciliation Test Project")
    yield proj
    # CASCADE removes the project, its execution_jobs, and their
    # execution_attempts.
    user = await session.get(User, proj.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


async def _make_job(
    session,
    project: Project,
    *,
    updated_at: datetime,
    status: ExecutionJobStatus = ExecutionJobStatus.VALIDATING,
) -> ExecutionJob:
    """Creates a job directly at the given `status`, with an explicit
    `updated_at`.

    `updated_at` has a `server_default` AND an `onupdate`, but neither
    fires on an explicit INSERT value -- passing it here is the only way
    to manufacture a genuinely old row without waiting out the real
    threshold, matching the pattern
    `test_execution_attempt_reconciliation.py` already established for
    `created_at`.
    """
    job = ExecutionJob(
        project_id=project.id,
        owner_id=project.owner_id,
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        capability=ExecutionCapability.ARRAY_COMPUTE,
        operation=ExecutionOperation.MATMUL,
        resource_class=ResourceClass.CLASS_ARRAY,
        parameters={},
        input_asset_ids=[],
        status=status,
        updated_at=updated_at,
    )
    session.add(job)
    await session.flush()
    await session.commit()
    return job


async def _make_pending_create_attempt(session, job: ExecutionJob) -> ExecutionAttempt:
    attempt_id = uuid.uuid4()
    attempt = ExecutionAttempt(
        id=attempt_id,
        execution_job_id=job.id,
        attempt_number=1,
        container_name=container_name_for_attempt(attempt_id),
        status=ExecutionAttemptStatus.PENDING_CREATE,
    )
    session.add(attempt)
    await session.flush()
    await session.commit()
    return attempt


def _stale_timestamp(*, margin_seconds: float = 60.0) -> datetime:
    """Older than the configured threshold, with margin."""
    return datetime.now(timezone.utc) - timedelta(
        seconds=settings.execution_job_validating_stale_after_seconds + margin_seconds
    )


def _fresh_timestamp() -> datetime:
    return datetime.now(timezone.utc)


async def _reload(job: ExecutionJob) -> ExecutionJob:
    """Re-read through an independent session -- the test session uses
    `expire_on_commit=False`, so reading the test's own cached instance
    would return pre-reconciliation state."""
    async with async_session_factory() as verify_session:
        reloaded = await verify_session.get(ExecutionJob, job.id)
        assert reloaded is not None
        return reloaded


# ---------------------------------------------------------------------------
# 1. A fresh VALIDATING job is not stale.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_validating_job_is_not_stale(session, project):
    job = await _make_job(session, project, updated_at=_fresh_timestamp())

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 0
    reloaded = await _reload(job)
    assert reloaded.reason is None
    assert reloaded.status is ExecutionJobStatus.VALIDATING


# ---------------------------------------------------------------------------
# 2. An old VALIDATING job is detected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_old_validating_job_is_detected(session, project):
    job = await _make_job(session, project, updated_at=_stale_timestamp())

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 1
    reloaded = await _reload(job)
    assert reloaded.reason == STALE_VALIDATING_JOB_DIAGNOSTIC


# ---------------------------------------------------------------------------
# 3. Every non-VALIDATING status is ignored, however old.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_validating_jobs_are_ignored(session, project):
    other_statuses = [
        ExecutionJobStatus.PENDING,
        ExecutionJobStatus.LAUNCHING,
        ExecutionJobStatus.RUNNING,
        ExecutionJobStatus.SUCCEEDED,
        ExecutionJobStatus.FAILED,
        ExecutionJobStatus.TIMED_OUT,
        ExecutionJobStatus.CANCEL_REQUESTED,
        ExecutionJobStatus.CANCELLED,
    ]
    jobs = [
        await _make_job(session, project, updated_at=_stale_timestamp(), status=status)
        for status in other_statuses
    ]

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 0
    for job, expected_status in zip(jobs, other_statuses):
        reloaded = await _reload(job)
        assert reloaded.status is expected_status
        assert reloaded.reason is None


# ---------------------------------------------------------------------------
# 4. Status is preserved.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validating_status_is_preserved(session, project):
    job = await _make_job(session, project, updated_at=_stale_timestamp())

    await reconcile_stale_validating_execution_jobs()

    reloaded = await _reload(job)
    assert reloaded.status is ExecutionJobStatus.VALIDATING
    assert reloaded.started_at is None
    assert reloaded.completed_at is None


# ---------------------------------------------------------------------------
# 5. The diagnostic is bounded, fixed, and free of database content.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostic_is_bounded_and_deterministic(session, project):
    job = await _make_job(session, project, updated_at=_stale_timestamp())

    await reconcile_stale_validating_execution_jobs()
    reloaded = await _reload(job)

    assert reloaded.reason == STALE_VALIDATING_JOB_DIAGNOSTIC
    assert STALE_VALIDATING_JOB_DIAGNOSTIC == (
        "Execution job remained in validating state beyond reconciliation threshold."
    )
    assert len(STALE_VALIDATING_JOB_DIAGNOSTIC) < 200
    assert "{" not in STALE_VALIDATING_JOB_DIAGNOSTIC and "%" not in STALE_VALIDATING_JOB_DIAGNOSTIC
    assert str(job.id) not in STALE_VALIDATING_JOB_DIAGNOSTIC
    assert str(project.id) not in STALE_VALIDATING_JOB_DIAGNOSTIC
    assert str(job.owner_id) not in STALE_VALIDATING_JOB_DIAGNOSTIC
    assert "docker" not in STALE_VALIDATING_JOB_DIAGNOSTIC.lower()


# ---------------------------------------------------------------------------
# 6. Repeatability: 1, then 0, then 0 -- with all fields stable.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_reconciliation_is_idempotent(session, project):
    job = await _make_job(session, project, updated_at=_stale_timestamp())

    first = await reconcile_stale_validating_execution_jobs()
    after_first = await _reload(job)
    second = await reconcile_stale_validating_execution_jobs()
    third = await reconcile_stale_validating_execution_jobs()
    after_third = await _reload(job)

    assert first == 1
    assert second == 0 and third == 0
    assert after_third.reason == after_first.reason
    assert after_third.status is after_first.status
    assert after_third.updated_at == after_first.updated_at
    assert after_third.created_at == after_first.created_at


# ---------------------------------------------------------------------------
# 6b. The explicit skip-check, not just the incidental query exclusion,
#     is what prevents a re-mark: force the row back into the query's
#     match window (simulating a job stuck long enough to cross the
#     threshold a second time) and confirm an already-diagnosed job is
#     still not re-marked or re-written.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_marked_job_reentering_the_stale_window_is_not_remarked(session, project):
    job = await _make_job(session, project, updated_at=_stale_timestamp())

    first = await reconcile_stale_validating_execution_jobs()
    assert first == 1
    after_first = await _reload(job)
    assert after_first.reason == STALE_VALIDATING_JOB_DIAGNOSTIC

    # Force updated_at back into the stale window directly (bypassing
    # onupdate, the same technique _make_job uses at INSERT) -- this is
    # what "the job stayed stuck long enough to cross the threshold
    # again" looks like at the database level, without waiting for real
    # time to pass.
    async with async_session_factory() as mutate_session:
        await mutate_session.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id == job.id)
            .values(updated_at=_stale_timestamp())
        )
        await mutate_session.commit()

    reselected = await ExecutionJobRepository(session).find_stale_validating_jobs(
        datetime.now(timezone.utc)
        - timedelta(seconds=settings.execution_job_validating_stale_after_seconds)
    )
    assert job.id in {j.id for j in reselected}  # proves the query WOULD match again

    second = await reconcile_stale_validating_execution_jobs()

    assert second == 0  # the explicit skip, not query exclusion, is what stopped this
    after_second = await _reload(job)
    assert after_second.reason == STALE_VALIDATING_JOB_DIAGNOSTIC


# ---------------------------------------------------------------------------
# 7. Multiple stale jobs are all detected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_stale_jobs_are_all_detected(session, project):
    jobs = [
        await _make_job(session, project, updated_at=_stale_timestamp(margin_seconds=60 + i))
        for i in range(3)
    ]

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 3
    for job in jobs:
        reloaded = await _reload(job)
        assert reloaded.reason == STALE_VALIDATING_JOB_DIAGNOSTIC
        assert reloaded.status is ExecutionJobStatus.VALIDATING

    async with async_session_factory() as verify_session:
        result = await verify_session.execute(
            select(ExecutionJob).where(ExecutionJob.id.in_([j.id for j in jobs]))
        )
        assert len(list(result.scalars().all())) == 3


# ---------------------------------------------------------------------------
# 8. Mixed population: only stale VALIDATING is selected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_population_selects_only_stale_validating(session, project):
    stale_validating = await _make_job(session, project, updated_at=_stale_timestamp())
    fresh_validating = await _make_job(session, project, updated_at=_fresh_timestamp())
    stale_pending = await _make_job(
        session, project, updated_at=_stale_timestamp(), status=ExecutionJobStatus.PENDING
    )
    stale_running = await _make_job(
        session, project, updated_at=_stale_timestamp(), status=ExecutionJobStatus.RUNNING
    )

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 1
    assert (await _reload(stale_validating)).reason == STALE_VALIDATING_JOB_DIAGNOSTIC
    for untouched in (fresh_validating, stale_pending, stale_running):
        assert (await _reload(untouched)).reason is None


# ---------------------------------------------------------------------------
# 9. A stale job WITH a PENDING_CREATE attempt: marked without touching
#    the attempt or using its existence to infer anything.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_job_with_existing_attempt_is_marked_without_inferring_docker_state(
    session, project
):
    job = await _make_job(session, project, updated_at=_stale_timestamp())
    attempt = await _make_pending_create_attempt(session, job)

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 1
    reloaded_job = await _reload(job)
    assert reloaded_job.reason == STALE_VALIDATING_JOB_DIAGNOSTIC
    assert reloaded_job.status is ExecutionJobStatus.VALIDATING

    # The attempt itself is completely untouched -- job-level
    # reconciliation never reads or writes ExecutionAttempt.
    async with async_session_factory() as verify_session:
        reloaded_attempt = await verify_session.get(ExecutionAttempt, attempt.id)
        assert reloaded_attempt is not None
        assert reloaded_attempt.status is ExecutionAttemptStatus.PENDING_CREATE
        assert reloaded_attempt.error_message is None
        assert reloaded_attempt.container_id is None


# ---------------------------------------------------------------------------
# 10. A stale job with NO attempt: marked without creating one.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_job_with_no_attempt_is_marked_without_creating_one(session, project):
    job = await _make_job(session, project, updated_at=_stale_timestamp())

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 1
    assert (await _reload(job)).reason == STALE_VALIDATING_JOB_DIAGNOSTIC

    async with async_session_factory() as verify_session:
        result = await verify_session.execute(
            select(ExecutionAttempt).where(ExecutionAttempt.execution_job_id == job.id)
        )
        assert list(result.scalars().all()) == []


# ---------------------------------------------------------------------------
# 11. No retry: row counts and identity fields are unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_never_retries(session, project):
    job = await _make_job(session, project, updated_at=_stale_timestamp())

    async with async_session_factory() as before_session:
        jobs_before = len(list((await before_session.execute(select(ExecutionJob))).scalars().all()))
        attempts_before = len(
            list((await before_session.execute(select(ExecutionAttempt))).scalars().all())
        )

    await reconcile_stale_validating_execution_jobs()

    async with async_session_factory() as after_session:
        jobs_after = len(list((await after_session.execute(select(ExecutionJob))).scalars().all()))
        attempts_after = len(
            list((await after_session.execute(select(ExecutionAttempt))).scalars().all())
        )

    assert jobs_after == jobs_before
    assert attempts_after == attempts_before

    reloaded = await _reload(job)
    assert reloaded.status is ExecutionJobStatus.VALIDATING  # never back to PENDING


# ---------------------------------------------------------------------------
# 12. The repository query itself is read-only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_query_filters_on_status_and_updated_at_and_is_read_only(session, project):
    stale = await _make_job(session, project, updated_at=_stale_timestamp())
    fresh = await _make_job(session, project, updated_at=_fresh_timestamp())

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.execution_job_validating_stale_after_seconds
    )
    found = await ExecutionJobRepository(session).find_stale_validating_jobs(cutoff)
    found_ids = {job.id for job in found}

    assert stale.id in found_ids
    assert fresh.id not in found_ids
    assert (await _reload(stale)).reason is None


# ---------------------------------------------------------------------------
# Timestamp boundary: strictly before cutoff, not at or after.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boundary_just_before_cutoff_is_stale(session, project):
    threshold = settings.execution_job_validating_stale_after_seconds
    job = await _make_job(
        session,
        project,
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=threshold + 5),
    )

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 1
    assert (await _reload(job)).reason == STALE_VALIDATING_JOB_DIAGNOSTIC


@pytest.mark.asyncio
async def test_boundary_just_after_cutoff_is_not_stale(session, project):
    threshold = settings.execution_job_validating_stale_after_seconds
    job = await _make_job(
        session,
        project,
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=threshold - 5),
    )

    marked = await reconcile_stale_validating_execution_jobs()

    assert marked == 0
    assert (await _reload(job)).reason is None


# ---------------------------------------------------------------------------
# 13. Structural: no Docker, no subprocess, no shell.
# ---------------------------------------------------------------------------


_FORBIDDEN_IMPORTS = {"docker", "subprocess", "socket", "shutil", "pty"}


def _imported_module_roots(path: Path) -> set[str]:
    """AST-based, not substring matching -- prose in a docstring that
    mentions Docker must not fail a security check about imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_reconciliation_implementation_imports_nothing_forbidden():
    backend = Path(__file__).resolve().parents[1]
    targets = [
        backend / "app" / "workers" / "reconciliation.py",
        backend / "app" / "modules" / "execution" / "repository.py",
        backend / "app" / "modules" / "execution" / "service.py",
        backend / "app" / "modules" / "execution" / "models.py",
        backend / "app" / "modules" / "execution" / "enums.py",
        backend / "app" / "modules" / "execution" / "schemas.py",
    ]
    for target in targets:
        assert target.exists(), target
        roots = _imported_module_roots(target)
        assert not (roots & _FORBIDDEN_IMPORTS), (target.name, roots & _FORBIDDEN_IMPORTS)


# ---------------------------------------------------------------------------
# 14. No Celery task/decorator was introduced.
# ---------------------------------------------------------------------------


def test_reconciliation_module_defines_no_celery_task():
    """AST-based, deliberately NOT a `sys.modules` check -- `conftest.py`
    imports `app.workers.celery_app` itself for FK registration, so
    celery is loaded process-wide regardless of this module and a
    `sys.modules` assertion would be a guaranteed false positive.
    """
    path = Path(__file__).resolve().parents[1] / "app" / "workers" / "reconciliation.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    assert "celery" not in _imported_module_roots(path)
    decorators = [
        ast.unparse(decorator)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
    ]
    assert decorators == [], decorators
