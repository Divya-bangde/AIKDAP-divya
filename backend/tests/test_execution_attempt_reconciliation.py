"""Sprint 16 Phase 7B.15 -- stale `ExecutionAttempt` reconciliation.

Root problem, structurally identical to the one Sprint 9J found for
`ResearchRun`: `prepare_approved_launch()` commits an `ExecutionAttempt`
at `PENDING_CREATE` *before* any Docker call (Phase 7B.12's recovery
protocol, deliberately), and nothing in the architecture ever revisits
that row. A launcher that dies before advancing it leaves it at
`PENDING_CREATE` forever.

`reconcile_stale_pending_execution_attempts()` is the first, deliberately
limited recovery mechanism: it detects those rows and records a bounded
diagnostic. It does NOT contact Docker, does NOT infer whether a
container exists, does NOT change status, and does NOT retry -- these
tests exist as much to pin down what it refuses to do as what it does.

Run against the REAL Postgres test database (see `conftest.py`), never
SQLite: the properties under test are real timestamp comparisons, a real
scoped UPDATE, and real idempotency across separate committed
transactions -- exactly what a mock would paper over.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.database.session import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.execution.enums import ExecutionAttemptStatus, ExecutionJobStatus
from app.modules.execution.models import ExecutionAttempt, ExecutionJob
from app.modules.execution.repository import ExecutionAttemptRepository
from app.modules.execution.service import container_name_for_attempt
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.workers.reconciliation import (
    STALE_ATTEMPT_DIAGNOSTIC,
    reconcile_stale_pending_execution_attempts,
)
from execution_launcher.models import ExecutionCapability, ExecutionOperation, ResourceClass


@pytest_asyncio.fixture(autouse=True)
async def _isolated_engine_and_clean_baseline():
    """Two independent concerns, deliberately in one fixture so their
    ordering cannot drift apart.

    `engine.dispose()` is the same narrow, test-local workaround the other
    `test_execution_*` files use for the repository's known
    module-level-engine + function-scoped-event-loop interaction. It does
    not touch `app/database/session.py`, `conftest.py`, or `pytest.ini`.

    The baseline reconciliation is the precedent
    `test_research_run_reconciliation.py` already established: this suite
    runs against the real database, which can contain stale attempts left
    by an earlier interrupted run. Reconciling once up front marks any of
    those, so they are no longer "newly marked" and cannot inflate the
    exact counts these tests assert. That is itself just an ordinary,
    idempotent use of the function under test -- not a workaround for it.
    """
    await engine.dispose()
    await reconcile_stale_pending_execution_attempts()
    yield


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-attemptrecon-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Attempt Reconciliation Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_attempt_reconciliation.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Attempt Reconciliation Test Project")
    yield proj
    # CASCADE removes the project, its execution_jobs, and their
    # execution_attempts -- so no row this suite creates survives to
    # become ambient staleness for a later run.
    user = await session.get(User, proj.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


async def _make_job(session, project: Project) -> ExecutionJob:
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
        status=ExecutionJobStatus.VALIDATING,
    )
    session.add(job)
    await session.flush()
    await session.commit()
    return job


async def _make_attempt(
    session,
    job: ExecutionJob,
    *,
    created_at: datetime,
    attempt_number: int = 1,
    status: ExecutionAttemptStatus = ExecutionAttemptStatus.PENDING_CREATE,
) -> ExecutionAttempt:
    """Creates an attempt directly, with an explicit `created_at`.

    `created_at` has a `server_default` but no Python-side default, so
    passing it explicitly puts it in the INSERT -- the only way to
    manufacture a genuinely old row without waiting out the real
    threshold. The container name is still derived through the real
    `container_name_for_attempt()`, not faked, so uniqueness behaves
    exactly as in production.
    """
    attempt_id = uuid.uuid4()
    attempt = ExecutionAttempt(
        id=attempt_id,
        execution_job_id=job.id,
        attempt_number=attempt_number,
        container_name=container_name_for_attempt(attempt_id),
        status=status,
        created_at=created_at,
    )
    session.add(attempt)
    await session.flush()
    await session.commit()
    return attempt


def _stale_timestamp() -> datetime:
    """Older than the configured threshold, with margin."""
    return datetime.now(timezone.utc) - timedelta(
        seconds=settings.execution_attempt_stale_after_seconds + 60
    )


def _fresh_timestamp() -> datetime:
    return datetime.now(timezone.utc)


async def _reload(attempt: ExecutionAttempt) -> ExecutionAttempt:
    """Re-read through an independent session.

    Reconciliation runs in its own session (`async_session_factory()`),
    and the test session uses `expire_on_commit=False`, so reading the
    test's own instance would return cached pre-reconciliation state.
    Every assertion below goes through the real committed row.
    """
    async with async_session_factory() as verify_session:
        reloaded = await verify_session.get(ExecutionAttempt, attempt.id)
        assert reloaded is not None
        return reloaded


# ---------------------------------------------------------------------------
# 1. A fresh PENDING_CREATE attempt is not stale.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_pending_attempt_is_not_stale(session, project):
    job = await _make_job(session, project)
    attempt = await _make_attempt(session, job, created_at=_fresh_timestamp())

    marked = await reconcile_stale_pending_execution_attempts()

    assert marked == 0
    reloaded = await _reload(attempt)
    assert reloaded.error_message is None
    assert reloaded.status is ExecutionAttemptStatus.PENDING_CREATE


# ---------------------------------------------------------------------------
# 2. An old PENDING_CREATE attempt is detected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_old_pending_attempt_is_detected(session, project):
    job = await _make_job(session, project)
    attempt = await _make_attempt(session, job, created_at=_stale_timestamp())

    marked = await reconcile_stale_pending_execution_attempts()

    assert marked == 1
    reloaded = await _reload(attempt)
    assert reloaded.error_message == STALE_ATTEMPT_DIAGNOSTIC


# ---------------------------------------------------------------------------
# 3. Non-PENDING_CREATE attempts are ignored, however old.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_pending_create_attempts_are_ignored(session, project):
    job = await _make_job(session, project)
    other_statuses = [
        ExecutionAttemptStatus.CREATED,
        ExecutionAttemptStatus.RUNNING,
        ExecutionAttemptStatus.EXITED,
        ExecutionAttemptStatus.UNKNOWN,
    ]
    attempts = [
        await _make_attempt(
            session, job, created_at=_stale_timestamp(), attempt_number=index + 1, status=status
        )
        for index, status in enumerate(other_statuses)
    ]

    marked = await reconcile_stale_pending_execution_attempts()

    assert marked == 0
    for attempt, expected_status in zip(attempts, other_statuses):
        reloaded = await _reload(attempt)
        assert reloaded.status is expected_status
        assert reloaded.error_message is None


# ---------------------------------------------------------------------------
# 4. The diagnostic is bounded, fixed, and free of database content.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostic_is_bounded_and_deterministic(session, project):
    job = await _make_job(session, project)
    attempt = await _make_attempt(session, job, created_at=_stale_timestamp())

    await reconcile_stale_pending_execution_attempts()
    after_first = await _reload(attempt)

    assert after_first.error_message == STALE_ATTEMPT_DIAGNOSTIC
    # Bounded: a fixed constant, short, with no interpolation of any kind.
    assert len(STALE_ATTEMPT_DIAGNOSTIC) < 200
    assert "{" not in STALE_ATTEMPT_DIAGNOSTIC and "%" not in STALE_ATTEMPT_DIAGNOSTIC
    # No database content reaches it -- nothing to inject through.
    assert str(attempt.id) not in STALE_ATTEMPT_DIAGNOSTIC
    assert attempt.container_name not in STALE_ATTEMPT_DIAGNOSTIC
    assert str(job.id) not in STALE_ATTEMPT_DIAGNOSTIC
    assert str(project.id) not in STALE_ATTEMPT_DIAGNOSTIC
    # No claim about Docker: it says what AIKDAP did not observe, never
    # that a container is absent or that Docker failed.
    assert "docker" not in STALE_ATTEMPT_DIAGNOSTIC.lower()

    # A second run must not append, rewrite, or otherwise disturb it.
    await reconcile_stale_pending_execution_attempts()
    after_second = await _reload(attempt)
    assert after_second.error_message == STALE_ATTEMPT_DIAGNOSTIC
    assert after_second.updated_at == after_first.updated_at


# ---------------------------------------------------------------------------
# 5. Multiple stale attempts are all processed, exactly once each.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_stale_attempts_are_all_processed(session, project):
    job = await _make_job(session, project)
    attempts = [
        await _make_attempt(session, job, created_at=_stale_timestamp(), attempt_number=number)
        for number in (1, 2, 3)
    ]

    marked = await reconcile_stale_pending_execution_attempts()

    assert marked == 3
    for attempt in attempts:
        reloaded = await _reload(attempt)
        assert reloaded.error_message == STALE_ATTEMPT_DIAGNOSTIC
        assert reloaded.status is ExecutionAttemptStatus.PENDING_CREATE

    # No duplicates: still exactly three attempt rows for this job.
    async with async_session_factory() as verify_session:
        result = await verify_session.execute(
            select(ExecutionAttempt).where(ExecutionAttempt.execution_job_id == job.id)
        )
        assert len(list(result.scalars().all())) == 3


# ---------------------------------------------------------------------------
# 6. A mixed population is filtered correctly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_population_selects_only_old_pending_create(session, project):
    job = await _make_job(session, project)
    old_pending = await _make_attempt(session, job, created_at=_stale_timestamp(), attempt_number=1)
    fresh_pending = await _make_attempt(session, job, created_at=_fresh_timestamp(), attempt_number=2)
    old_created = await _make_attempt(
        session, job, created_at=_stale_timestamp(), attempt_number=3,
        status=ExecutionAttemptStatus.CREATED,
    )
    old_running = await _make_attempt(
        session, job, created_at=_stale_timestamp(), attempt_number=4,
        status=ExecutionAttemptStatus.RUNNING,
    )

    marked = await reconcile_stale_pending_execution_attempts()

    assert marked == 1
    assert (await _reload(old_pending)).error_message == STALE_ATTEMPT_DIAGNOSTIC
    for untouched in (fresh_pending, old_created, old_running):
        assert (await _reload(untouched)).error_message is None


# ---------------------------------------------------------------------------
# 7. Attempts on an unrelated job are not collaterally modified.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attempts_on_other_jobs_are_not_collaterally_modified(session, project):
    """The operation is deliberately global rather than job- or
    project-scoped (matching `reconcile_stale_research_runs`): this is
    deployment-wide infrastructure recovery, not a tenant-scoped read.
    What must hold is that selection is driven ONLY by
    status + `created_at` -- a second job's non-matching attempts stay
    untouched, and its genuinely stale one is legitimately reconciled.
    """
    stale_job = await _make_job(session, project)
    other_job = await _make_job(session, project)

    stale_here = await _make_attempt(session, stale_job, created_at=_stale_timestamp())
    fresh_there = await _make_attempt(session, other_job, created_at=_fresh_timestamp(), attempt_number=1)
    running_there = await _make_attempt(
        session, other_job, created_at=_stale_timestamp(), attempt_number=2,
        status=ExecutionAttemptStatus.RUNNING,
    )
    stale_there = await _make_attempt(session, other_job, created_at=_stale_timestamp(), attempt_number=3)

    marked = await reconcile_stale_pending_execution_attempts()

    assert marked == 2
    assert (await _reload(stale_here)).error_message == STALE_ATTEMPT_DIAGNOSTIC
    assert (await _reload(stale_there)).error_message == STALE_ATTEMPT_DIAGNOSTIC
    assert (await _reload(fresh_there)).error_message is None
    assert (await _reload(running_there)).error_message is None
    # Neither job's own status is touched -- job lifecycle is not this
    # function's business.
    async with async_session_factory() as verify_session:
        for job in (stale_job, other_job):
            reloaded_job = await verify_session.get(ExecutionJob, job.id)
            assert reloaded_job is not None
            assert reloaded_job.status is ExecutionJobStatus.VALIDATING


# ---------------------------------------------------------------------------
# 8. No retry: nothing is created, no attempt_number moves.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_never_retries(session, project):
    job = await _make_job(session, project)
    attempt = await _make_attempt(session, job, created_at=_stale_timestamp())

    async with async_session_factory() as before_session:
        jobs_before = len(list((await before_session.execute(select(ExecutionJob))).scalars().all()))
        attempts_before = len(list((await before_session.execute(select(ExecutionAttempt))).scalars().all()))

    await reconcile_stale_pending_execution_attempts()

    async with async_session_factory() as after_session:
        jobs_after = len(list((await after_session.execute(select(ExecutionJob))).scalars().all()))
        attempts_after = len(list((await after_session.execute(select(ExecutionAttempt))).scalars().all()))

    assert jobs_after == jobs_before
    assert attempts_after == attempts_before

    reloaded = await _reload(attempt)
    assert reloaded.attempt_number == 1
    assert reloaded.container_id is None
    # The job is NOT returned to PENDING -- that would make a stale
    # attempt automatically re-claimable, i.e. an implicit retry.
    async with async_session_factory() as verify_session:
        reloaded_job = await verify_session.get(ExecutionJob, job.id)
        assert reloaded_job is not None
        assert reloaded_job.status is ExecutionJobStatus.VALIDATING


# ---------------------------------------------------------------------------
# 9. No status guessing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_attempt_status_is_never_guessed(session, project):
    job = await _make_job(session, project)
    attempt = await _make_attempt(session, job, created_at=_stale_timestamp())

    await reconcile_stale_pending_execution_attempts()

    reloaded = await _reload(attempt)
    # Age is not evidence about Docker. The row keeps the only status
    # this system can honestly assert.
    assert reloaded.status is ExecutionAttemptStatus.PENDING_CREATE
    assert reloaded.container_id is None
    assert reloaded.exit_code is None
    assert reloaded.started_at is None
    assert reloaded.completed_at is None


# ---------------------------------------------------------------------------
# 10. Repeated runs are harmless.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_reconciliation_is_idempotent(session, project):
    job = await _make_job(session, project)
    attempt = await _make_attempt(session, job, created_at=_stale_timestamp())

    first = await reconcile_stale_pending_execution_attempts()
    after_first = await _reload(attempt)
    second = await reconcile_stale_pending_execution_attempts()
    third = await reconcile_stale_pending_execution_attempts()
    after_third = await _reload(attempt)

    assert first == 1
    assert second == 0 and third == 0
    assert after_third.error_message == after_first.error_message
    assert after_third.status is after_first.status
    assert after_third.updated_at == after_first.updated_at
    assert after_third.created_at == after_first.created_at
    assert after_third.attempt_number == after_first.attempt_number


# ---------------------------------------------------------------------------
# 11. The repository query itself filters on exactly two conditions.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_query_filters_on_status_and_created_at(session, project):
    job = await _make_job(session, project)
    stale = await _make_attempt(session, job, created_at=_stale_timestamp(), attempt_number=1)
    fresh = await _make_attempt(session, job, created_at=_fresh_timestamp(), attempt_number=2)

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.execution_attempt_stale_after_seconds
    )
    found = await ExecutionAttemptRepository(session).find_stale_pending_attempts(cutoff)
    found_ids = {attempt.id for attempt in found}

    assert stale.id in found_ids
    assert fresh.id not in found_ids
    # A read-only query: it must not have modified what it selected.
    assert (await _reload(stale)).error_message is None


# ---------------------------------------------------------------------------
# 12. Structural: no Docker, no subprocess, no shell, no Celery task.
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


def test_reconciliation_module_defines_no_celery_task():
    """No Celery task, queue, or route is introduced here. Asserted by
    AST, deliberately NOT via `sys.modules` -- `conftest.py` imports
    `app.workers.celery_app` itself for FK registration, so celery is
    loaded process-wide regardless of this module and a `sys.modules`
    check would be a guaranteed false positive.
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
