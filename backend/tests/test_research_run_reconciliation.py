"""Sprint 9J: stale `ResearchRun` reconciliation.

Root problem: `ResearchExecutionService.execute()` sets
`status=RUNNING` before doing any real work, and only reaches
`_complete()`/`_fail()` if its own process survives to run them. A
worker crash, OOM kill, or container restart mid-run skips both,
leaving the row at `RUNNING` forever -- confirmed live against this
deployment's own history (a run from an interrupted manual test was
still `RUNNING` days later). `reconcile_stale_research_runs()` is the
recovery mechanism; these tests run against the real Postgres test
database (see `conftest.py`), not a mock, because the property under
test -- "a scoped, idempotent UPDATE against real rows" -- is exactly
what a mock would paper over.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.core.config import settings
from app.modules.research.enums import ResearchRunStatus
from app.modules.research.models import ResearchRun
from app.workers.reconciliation import (
    STALE_RUN_FAILURE_REASON,
    reconcile_stale_research_runs,
)


@pytest_asyncio.fixture(autouse=True)
async def clean_ambient_stale_runs():
    """This suite runs against the real database (see `conftest.py`),
    which can genuinely contain stale runs from outside this test
    module -- Sprint 9J's own audit found one from an interrupted
    Sprint 9H manual test. Reconciling once before each test gives
    every test a known-clean baseline to assert exact counts against,
    which is itself just an ordinary (idempotent) use of the function
    under test, not a workaround."""
    await reconcile_stale_research_runs()


async def _make_run(session, project, *, started_at: datetime, status=ResearchRunStatus.RUNNING) -> ResearchRun:
    run = ResearchRun(
        project_id=project.id,
        owner_id=project.owner_id,
        query="Sprint 9J reconciliation test query",
        status=status,
        started_at=started_at,
    )
    session.add(run)
    await session.flush()
    await session.commit()
    return run


def _stale_timestamp() -> datetime:
    """Older than the configured threshold, with margin."""
    return datetime.now(timezone.utc) - timedelta(
        seconds=settings.research_run_stale_after_seconds + 60
    )


def _fresh_timestamp() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Phase 13 — a genuinely stale run is recovered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stale_running_run_is_marked_failed_with_a_safe_reason(session, project):
    run = await _make_run(session, project, started_at=_stale_timestamp())

    reconciled_count = await reconcile_stale_research_runs()

    await session.refresh(run)
    assert reconciled_count == 1
    assert run.status is ResearchRunStatus.FAILED
    assert run.error_message == STALE_RUN_FAILURE_REASON
    assert run.completed_at is not None
    assert run.duration_ms is not None and run.duration_ms > 0
    # Phase 13: no fabricated deliverable.
    assert run.final_answer is None
    assert not run.citations


@pytest.mark.asyncio
async def test_the_recovery_reason_never_contains_infrastructure_detail(session, project):
    """Phase 12: safe for an API consumer to read as-is."""
    run = await _make_run(session, project, started_at=_stale_timestamp())

    await reconcile_stale_research_runs()

    await session.refresh(run)
    forbidden = ("Traceback", "Redis", "Postgres", "celery@", "0x", "Exception:")
    assert not any(marker in run.error_message for marker in forbidden)


# ---------------------------------------------------------------------------
# Phase 14 — an active run is never touched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_freshly_started_running_run_is_left_alone(session, project):
    run = await _make_run(session, project, started_at=_fresh_timestamp())

    reconciled_count = await reconcile_stale_research_runs()

    await session.refresh(run)
    assert reconciled_count == 0
    assert run.status is ResearchRunStatus.RUNNING
    assert run.error_message is None
    assert run.completed_at is None


@pytest.mark.asyncio
async def test_a_run_just_inside_the_threshold_is_left_alone(session, project):
    """The boundary case: `started_at` just younger than the cutoff
    must not be reaped -- the reaper must not be trigger-happy at the
    edge of its own configured window."""
    just_inside = datetime.now(timezone.utc) - timedelta(
        seconds=settings.research_run_stale_after_seconds - 5
    )
    run = await _make_run(session, project, started_at=just_inside)

    reconciled_count = await reconcile_stale_research_runs()

    await session.refresh(run)
    assert reconciled_count == 0
    assert run.status is ResearchRunStatus.RUNNING


@pytest.mark.asyncio
async def test_completed_and_failed_runs_are_never_touched_regardless_of_age(session, project):
    """The status filter, not just the age filter, must hold — an old
    but legitimately-finished run is not "stale"."""
    old_completed = await _make_run(
        session, project, started_at=_stale_timestamp(), status=ResearchRunStatus.COMPLETED
    )
    old_failed = await _make_run(
        session, project, started_at=_stale_timestamp(), status=ResearchRunStatus.FAILED
    )

    reconciled_count = await reconcile_stale_research_runs()

    await session.refresh(old_completed)
    await session.refresh(old_failed)
    assert reconciled_count == 0
    assert old_completed.status is ResearchRunStatus.COMPLETED
    assert old_failed.status is ResearchRunStatus.FAILED


# ---------------------------------------------------------------------------
# Phase 15 — idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciling_twice_only_mutates_once(session, project):
    run = await _make_run(session, project, started_at=_stale_timestamp())

    first_pass = await reconcile_stale_research_runs()
    await session.refresh(run)
    first_completed_at = run.completed_at

    second_pass = await reconcile_stale_research_runs()
    await session.refresh(run)

    assert first_pass == 1
    assert second_pass == 0
    # completed_at must not have been overwritten by the second pass.
    assert run.completed_at == first_completed_at
    assert run.status is ResearchRunStatus.FAILED


# ---------------------------------------------------------------------------
# Phase 16 (isolation half) — reconciliation scopes correctly across runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_only_touches_the_stale_run_among_several(session, project):
    stale = await _make_run(session, project, started_at=_stale_timestamp())
    active = await _make_run(session, project, started_at=_fresh_timestamp())
    already_done = await _make_run(
        session, project, started_at=_stale_timestamp(), status=ResearchRunStatus.COMPLETED
    )

    reconciled_count = await reconcile_stale_research_runs()

    await session.refresh(stale)
    await session.refresh(active)
    await session.refresh(already_done)
    assert reconciled_count == 1
    assert stale.status is ResearchRunStatus.FAILED
    assert active.status is ResearchRunStatus.RUNNING
    assert already_done.status is ResearchRunStatus.COMPLETED
