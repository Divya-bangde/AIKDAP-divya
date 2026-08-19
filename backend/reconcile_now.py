"""Sprint 9J Phase 17: reconcile the genuinely worker-killed run right
now, without waiting the full configured 20-minute threshold, by
temporarily treating any RUNNING row as eligible. This proves the
mechanism recovers a *real* crash-produced row -- the threshold's own
correctness (not reaping recent runs) is already covered by the
pytest suite and is not what this check is for."""
import asyncio

import app.workers.celery_app  # noqa: F401 -- registers ORM models on Base.metadata, exactly as worker.py does
from app.core.config import settings

settings.research_run_stale_after_seconds = 0.001

from app.workers.reconciliation import reconcile_stale_research_runs


async def main():
    count = await reconcile_stale_research_runs()
    print(f"reconciled {count} run(s)")


asyncio.run(main())
