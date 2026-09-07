"""Sprint 16 Phase 8.0 -- a genuinely separate OS process dispatches the
real Docker-aware reconciliation Celery task over the real Redis broker.

No HTTP entry point exists for reconciliation (by design, Phase 7B.29
scoped it to automatic startup detection only) -- this is the
documented exception to "use the router": the smallest real boundary
available is the Celery task dispatch itself, which this script
performs exactly as any other real enqueuer in the app would.
"""
import sys

from app.workers.tasks import reconcile_execution_attempt

result = reconcile_execution_attempt.delay(sys.argv[1])
print(f"TASK_ID={result.id}")
