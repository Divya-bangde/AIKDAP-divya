"""Celery worker process entry point.

This is the `-A` (app) target Docker and the CLI use:

    celery -A app.workers.worker worker --loglevel=info

Responsibilities that belong here rather than in `celery_app.py`:
configuring the app's own structured logging for this process, and
explicitly importing the task modules so `celery -A app.workers.worker
inspect registered` reflects them immediately — `celery_app.py`'s
`autodiscover_tasks` calls already do this lazily on worker startup,
so the imports below are redundant-but-explicit rather than load-bearing,
matching the "explicit is better than implicit" register-tasks
responsibility called out for this module.

`app` is deliberately the name of the re-exported Celery instance:
Celery's `-A` flag looks for an attribute named `app` (or `celery`) in
the target module by convention, and `app = celery_app` is what makes
`-A app.workers.worker` resolve correctly.
"""

import asyncio

from celery.signals import worker_ready

from app.core.logging.logger import configure_logging, get_logger
from app.workers.celery_app import celery_app

configure_logging()
logger = get_logger(__name__)

# Explicit registration (see module docstring) — both modules register
# their tasks on `celery_app` purely by being imported.
import app.workers.tasks  # noqa: E402,F401
import app.workers.scheduler  # noqa: E402,F401
from app.workers.reconciliation import reconcile_stale_research_runs_on_startup  # noqa: E402

app = celery_app


@worker_ready.connect
def _reconcile_on_startup(**_kwargs: object) -> None:
    """Sprint 9J: recover any `ResearchRun` left at `RUNNING` by a
    previous instance of this worker that never returned (crash, OOM,
    container restart). Runs once, after Celery reports this process
    ready to accept tasks — see `app.workers.reconciliation` for why
    this replaces a Celery Beat schedule this project does not have.
    """
    asyncio.run(reconcile_stale_research_runs_on_startup())


logger.info(
    "worker_process_initialized",
    registered_tasks=sorted(
        name for name in celery_app.tasks if not name.startswith("celery.")
    ),
)
