"""Sprint 9J: recovers `ResearchRun` rows orphaned by a worker
interruption.

`ResearchExecutionService.execute()` sets `status=RUNNING` before doing
any real work and only reaches `_complete()`/`_fail()` if its own
Python process survives long enough to run them (see
`app.modules.research.service`). A worker crash, an OOM kill, or a
container restart mid-run skips both of those, and nothing in the
architecture ever revisits the row afterward -- confirmed live: a run
from an earlier interrupted manual test was still sitting at `RUNNING`
days later, with no active task claiming it.

This module does not run automatically as a cron: like
`app.workers.scheduler`'s existing `retry_failed_tasks`, this project
has no active Celery Beat schedule (`celery_app.py` defines no
`beat_schedule`, and no `beat` service exists in `docker-compose.yml`),
so adding one just for this single lightweight check would be
infrastructure the measurements do not justify. Instead,
`reconcile_stale_research_runs_on_startup()` runs once per worker
process, via Celery's own `worker_ready` signal (wired up in
`app.workers.worker`) -- the same "startup reconciliation" pattern
Sprint 9H already established for the API process
(`app.core.llm.startup_validation.run_startup_validation`, run from
FastAPI's lifespan). A worker that crashed and restarted reconciles its
own orphans the moment it comes back up; a long-lived worker that never
crashes never needs to.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.logging.logger import get_logger
from app.database.session import async_session_factory
from app.modules.research.enums import ResearchRunStatus
from app.modules.research.models import ResearchRun

logger = get_logger(__name__)

#: Persisted on every run this reconciles. Deliberately free of stack
#: traces, task ids, or infrastructure detail -- this string reaches
#: `GET /research/runs/{id}` unauthenticated-adjacent to nothing (the
#: endpoint requires auth, but `error_message` is still user-facing),
#: so it says what happened without saying anything about *why* the
#: worker died.
STALE_RUN_FAILURE_REASON = (
    "Research run marked failed during stale-run reconciliation after "
    "worker interruption."
)


async def reconcile_stale_research_runs() -> int:
    """Fail every `ResearchRun` stuck at `RUNNING` past the stale
    threshold. Returns the number of runs reconciled.

    Scoped, not blind: only rows that are *both* `status=RUNNING` *and*
    `started_at` older than `settings.research_run_stale_after_seconds`
    are touched. `execute()` sets `started_at` fresh at the top of
    every attempt -- including every Celery-level retry -- so a run
    that is genuinely still in progress always has a recent
    `started_at` and can never match this query, no matter how long
    its *first* attempt was queued for.

    Idempotent by construction rather than by a lock: the WHERE clause
    only ever matches rows still at `RUNNING`, and this function is the
    only thing that ever moves a row *out* of `RUNNING` without also
    completing it -- so a second call in the same process, or a second
    worker process reconciling at the same moment, finds nothing left
    to touch (or, in the concurrent case, a normal per-row database
    update race that Postgres itself resolves safely; no additional
    locking is added for a single-worker-instance deployment where that
    race does not occur in practice).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.research_run_stale_after_seconds
    )

    async with async_session_factory() as session:
        result = await session.execute(
            select(ResearchRun).where(
                ResearchRun.status == ResearchRunStatus.RUNNING,
                ResearchRun.started_at < cutoff,
            )
        )
        stale_runs = list(result.scalars().all())

        now = datetime.now(timezone.utc)
        for run in stale_runs:
            # A real, non-fabricated number: how long this row actually
            # existed as "running" before reconciliation closed it out.
            # Not a claim about when the underlying work actually
            # stopped -- the worker may have died earlier -- only about
            # when this row was last known to be in progress.
            duration_ms = (
                int((now - run.started_at).total_seconds() * 1000)
                if run.started_at
                else None
            )
            run.status = ResearchRunStatus.FAILED
            run.error_message = STALE_RUN_FAILURE_REASON
            run.completed_at = now
            run.duration_ms = duration_ms
            logger.warning(
                "research_run_reconciled_stale",
                run_id=str(run.id),
                started_at=run.started_at.isoformat() if run.started_at else None,
                stale_after_seconds=settings.research_run_stale_after_seconds,
            )

        if stale_runs:
            await session.commit()

    return len(stale_runs)


async def reconcile_stale_research_runs_on_startup() -> None:
    """Entry point for the worker's `worker_ready` signal handler.

    Never raises -- a reconciliation failure must not prevent the
    worker from accepting new tasks, the same non-fatal contract
    `run_startup_validation` uses on the API side.
    """
    try:
        count = await reconcile_stale_research_runs()
    except Exception as exc:  # noqa: BLE001 - startup path must not crash the worker
        logger.error(
            "research_run_reconciliation_failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return

    logger.info("research_run_reconciliation_summary", reconciled_count=count)
