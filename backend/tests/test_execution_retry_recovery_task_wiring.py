"""Sprint 16 Phase 7B.22 -- wiring active retry recovery.

Phase 7B.21 proved `recover_interrupted_retry_attempt`'s claim-and-
materialize transaction is safe under real concurrency, but nothing
ever called it: `reconcile_stale_launching_execution_jobs` was
detection-only and not wired into worker startup. This phase makes it
DO something -- detection now enqueues a Celery task per stale job,
and the task (not the reconciler) is the only place that runs the
guard pipeline and the 7B.21 transaction.

This file proves two things stay separate:
  - `reconcile_stale_launching_execution_jobs` (startup, one event
    loop, must stay fast and never raise) touches only the DB query and
    `.delay()` -- it never runs guard-pipeline I/O (V1, V5).
  - `workers.tasks.recover_execution_job_retry` (off the startup loop)
    is where `recover_interrupted_retry_attempt` actually runs, and is
    idempotent/non-retrying by construction (V3, V4).

V2 proves the reconciler's own "never raises" contract holds when the
one thing it still does -- the DB query -- fails.

Tasks are invoked directly as bound calls (`recover_execution_job_retry(job_id)`),
not through `.delay()`/a broker -- the standard way to unit test a
Celery task body in-process: `bind=True` makes the decorated name a
`Task` instance whose `__call__` runs the wrapped function synchronously
with `self` bound, with no broker/backend involved.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from app.database.session import async_session_factory, engine
from app.modules.assets.enums import AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.auth.models import User
from app.modules.execution import service as execution_service_module
from app.modules.execution.enums import ExecutionJobStatus
from app.modules.execution.models import ExecutionAttempt, ExecutionJob
from app.modules.execution.repository import ExecutionJobRepository
from app.modules.execution.service import STALE_LAUNCHING_JOB_DIAGNOSTIC, container_name_for_attempt
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.workers import reconciliation as reconciliation_module
from app.workers.reconciliation import reconcile_stale_launching_execution_jobs
from app.workers.tasks import recover_execution_job_retry
from execution_launcher.models import ExecutionCapability, ExecutionOperation, ResourceClass


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_between_tests():
    await engine.dispose()
    yield


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-retrywiring-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Retry Recovery Wiring Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_retry_recovery_task_wiring.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Retry Recovery Wiring Test Project")
    yield proj
    user = await session.get(User, proj.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


async def _resolvable_asset(session, project: Project, *, filename: str) -> Asset:
    storage = get_storage_provider()
    storage_path = await storage.save(project_id=project.id, filename=filename, content=b"1,2\n3,4\n")
    asset = Asset(
        project_id=project.id,
        owner_id=project.owner_id,
        title=filename,
        file_name=filename,
        file_extension=filename.rsplit(".", 1)[-1],
        mime_type="text/csv",
        file_size=0,
        storage_path=storage_path,
        checksum="test-checksum",
        asset_type=AssetType.DATASET,
        status=AssetStatus.ACTIVE,
        source=AssetSource.UPLOAD,
        tags=[],
    )
    created = await AssetRepository(session).create(asset)
    await session.commit()
    return created


async def _make_launching_job(
    session, project: Project, *, input_asset_ids: list[uuid.UUID], stale: bool = True
) -> ExecutionJob:
    """A `LAUNCHING` job with a pre-existing "attempt 1", `updated_at`
    pushed comfortably past the staleness cutoff by default (detection
    tests need it stale; task-level tests don't care -- the task
    doesn't re-check staleness, only the reconciler's query does)."""
    from datetime import datetime, timedelta, timezone

    from app.core.config import settings

    now = datetime.now(timezone.utc)
    updated_at = (
        now - timedelta(seconds=settings.execution_job_validating_stale_after_seconds + 60)
        if stale
        else now
    )

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
        updated_at=updated_at,
    )
    session.add(job)
    await session.flush()
    first = ExecutionAttempt(
        execution_job_id=job.id,
        attempt_number=1,
        container_name=container_name_for_attempt(uuid.uuid4()),
        created_at=updated_at - timedelta(seconds=60),
    )
    session.add(first)
    await session.flush()
    await session.commit()
    await session.refresh(job)
    return job


async def _reload_job(job_id: uuid.UUID) -> ExecutionJob:
    async with async_session_factory() as verify_session:
        job = await verify_session.get(ExecutionJob, job_id)
        assert job is not None
        return job


async def _with_resolvable_asset(session, project: Project, *, filename: str) -> list[uuid.UUID]:
    asset = await _resolvable_asset(session, project, filename=filename)
    return [asset.id]


async def _setup_stale_job(*, input_asset_ids: list[uuid.UUID] | None = None) -> tuple[Project, ExecutionJob]:
    """V3/V4 run the task body as a real bound Celery call
    (`recover_execution_job_retry(...)`, not `.delay()`), which itself
    calls `asyncio.run()` internally (`_run_task_loop`) -- so, like
    `test_celery_task_event_loop.py`, those tests must be plain `def`,
    not `async def` (a nested `asyncio.run()` inside an already-running
    loop raises). Setup/verify/teardown here each get their own
    top-level `asyncio.run()` call instead of the `session`/`project`
    fixtures, relying on `db_pool_pre_ping` (settings default `True`) to
    transparently discard/reconnect any pooled connection left bound to
    a now-closed prior loop -- the same tolerance real sequential Celery
    task invocations depend on in production.
    """
    async with async_session_factory() as session:
        project = await _make_owner_and_project(session, name="Retry Recovery Wiring Test Project")
        ids = input_asset_ids
        if ids is None:
            ids = await _with_resolvable_asset(session, project, filename="task-wiring.csv")
        job = await _make_launching_job(session, project, input_asset_ids=ids)
        return project, job


async def _teardown_project(project: Project) -> None:
    async with async_session_factory() as session:
        user = await session.get(User, project.owner_id)
        if user is not None:
            await session.delete(user)
            await session.commit()


async def _attempt_numbers_for_job(job_id: uuid.UUID) -> list[int]:
    async with async_session_factory() as verify_session:
        from sqlalchemy import select

        result = await verify_session.execute(
            select(ExecutionAttempt.attempt_number)
            .where(ExecutionAttempt.execution_job_id == job_id)
            .order_by(ExecutionAttempt.attempt_number)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# V1 -- N stale jobs -> exactly N enqueued tasks, zero guard-pipeline calls.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_reconciler_enqueues_exactly_n_tasks_and_touches_no_guard_pipeline(
    session, project, monkeypatch
):
    asset = await _resolvable_asset(session, project, filename="v1.csv")
    jobs = [
        await _make_launching_job(session, project, input_asset_ids=[asset.id])
        for _ in range(3)
    ]

    delay_mock = MagicMock()
    monkeypatch.setattr(recover_execution_job_retry, "delay", delay_mock)

    guard_calls = MagicMock(side_effect=AssertionError("guard pipeline must not run during startup reconciliation"))
    monkeypatch.setattr(execution_service_module, "build_candidate", guard_calls)
    monkeypatch.setattr(execution_service_module, "validate_and_approve", guard_calls)

    enqueued = await reconcile_stale_launching_execution_jobs()

    assert enqueued == 3
    assert delay_mock.call_count == 3
    enqueued_ids = {call.args[0] for call in delay_mock.call_args_list}
    assert enqueued_ids == {str(job.id) for job in jobs}
    guard_calls.assert_not_called()


# ---------------------------------------------------------------------------
# V2 -- the reconciler never raises when its DB query fails.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_reconciler_never_raises_when_db_query_fails(monkeypatch, caplog):
    async def _boom(self, cutoff):
        raise RuntimeError("synthetic DB failure")

    monkeypatch.setattr(ExecutionJobRepository, "find_stale_launching_jobs", _boom)

    with caplog.at_level("ERROR"):
        result = await reconcile_stale_launching_execution_jobs()  # must not raise

    assert result == 0
    assert any(
        "execution_job_launching_reconciliation_failed" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# V3 -- the task, run twice for the same job, creates exactly one attempt.
# Second call returns cleanly (no exception -> no Celery retry).
# ---------------------------------------------------------------------------


def test_v3_task_run_twice_creates_exactly_one_attempt_no_retry():
    project, job = asyncio.run(_setup_stale_job())
    try:
        first_result = recover_execution_job_retry(str(job.id))
        second_result = recover_execution_job_retry(str(job.id))  # must not raise

        assert first_result["status"] == "recovered"
        assert second_result["status"] == "lost_race"

        assert asyncio.run(_attempt_numbers_for_job(job.id)) == [1, 2]
    finally:
        asyncio.run(_teardown_project(project))


# ---------------------------------------------------------------------------
# V4 -- guard rejection inside the task -> job.reason set, no attempt,
# no exception (so no Celery retry).
# ---------------------------------------------------------------------------


def test_v4_guard_rejection_inside_task_sets_reason_no_attempt_no_retry():
    unresolvable_asset_id = uuid.uuid4()  # no backing Asset row -> InputResolutionError
    project, job = asyncio.run(_setup_stale_job(input_asset_ids=[unresolvable_asset_id]))
    try:
        result = recover_execution_job_retry(str(job.id))  # must not raise

        assert result["status"] == "guard_rejected"

        reloaded = asyncio.run(_reload_job(job.id))
        assert reloaded.reason == STALE_LAUNCHING_JOB_DIAGNOSTIC
        assert asyncio.run(_attempt_numbers_for_job(job.id)) == [1], "no attempt materialized from a rejected guard"
    finally:
        asyncio.run(_teardown_project(project))


# ---------------------------------------------------------------------------
# V5 -- startup path timing: the reconciler completes fast and never
# touches build_candidate/validate_and_approve, even with several jobs.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v5_startup_path_never_touches_guard_pipeline_and_stays_fast(
    session, project, monkeypatch
):
    asset = await _resolvable_asset(session, project, filename="v5.csv")
    for _ in range(5):
        await _make_launching_job(session, project, input_asset_ids=[asset.id])

    monkeypatch.setattr(recover_execution_job_retry, "delay", MagicMock())

    guard_calls = MagicMock(side_effect=AssertionError("guard pipeline must not run on the startup path"))
    monkeypatch.setattr(execution_service_module, "build_candidate", guard_calls)
    monkeypatch.setattr(execution_service_module, "validate_and_approve", guard_calls)

    started = time.monotonic()
    enqueued = await reconcile_stale_launching_execution_jobs()
    elapsed = time.monotonic() - started

    assert enqueued == 5
    guard_calls.assert_not_called()
    # Generous bound: a real guard pipeline run (asset I/O, resolver
    # round trips) takes materially longer than a bare query + 5
    # in-process `.delay()` mock calls. This is a coarse sanity check,
    # not the safety proof -- guard_calls.assert_not_called() above is.
    assert elapsed < 2.0, f"reconciler took {elapsed:.3f}s -- too slow for a detection-only pass"


# ---------------------------------------------------------------------------
# Structural: reconciliation.py's launching-job path no longer imports
# the guard-pipeline/service internals it used to call inline.
# ---------------------------------------------------------------------------


def test_reconciliation_module_no_longer_imports_recover_interrupted_retry_attempt():
    assert not hasattr(reconciliation_module, "recover_interrupted_retry_attempt")
    assert not hasattr(reconciliation_module, "ExecutionRetryClaimSupersededError")
