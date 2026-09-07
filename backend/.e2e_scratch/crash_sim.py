"""Sprint 16 Phase 8.0 -- genuinely separate OS process crash simulation.

Called as its own python invocation (see run_crash.sh), NOT imported.
Performs the real prepare_approved_launch() guard pipeline through
docker create()/start() and durable RUNNING persistence, then exits
WITHOUT ever calling wait()/finalize -- the real crash window Phase
7B.29's Docker-aware reconciliation exists to recover from.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone

import app.workers.celery_app  # registers every ORM model on Base.metadata
from app.database.session import async_session_factory
from app.modules.execution.enums import ExecutionAttemptStatus, ExecutionJobStatus
from app.modules.execution.repository import ExecutionAttemptRepository, ExecutionJobRepository
from app.modules.execution.service import prepare_approved_launch
from execution_launcher.launcher import _docker_create_kwargs
import docker


async def main(job_id_str: str) -> None:
    job_id = uuid.UUID(job_id_str)
    async with async_session_factory() as session:
        preparation = await prepare_approved_launch(job_id, session)
        approved = preparation.approved_spec

        attempts = ExecutionAttemptRepository(session)
        jobs = ExecutionJobRepository(session)
        attempt = await attempts.get_by_id(preparation.attempt_id)
        job = await jobs.get_by_id(job_id)

        kwargs = _docker_create_kwargs(approved, container_name=attempt.container_name)
        client = docker.from_env()
        container = client.containers.create(**kwargs)
        attempt.container_id = container.id
        attempt.status = ExecutionAttemptStatus.CREATED
        await session.commit()

        container.start()
        container.reload()
        attempt.status = ExecutionAttemptStatus.RUNNING
        attempt.started_at = datetime.now(timezone.utc)
        job.status = ExecutionJobStatus.RUNNING
        job.started_at = attempt.started_at
        await session.commit()

        print(f"ATTEMPT_ID={attempt.id}")
        print(f"CONTAINER_ID={container.id}")
        print(f"CONTAINER_NAME={attempt.container_name}")
    # Deliberately exits here -- no wait(), no finalize. Simulates the
    # worker process crashing mid-execution, immediately after the
    # container was confirmed RUNNING.


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
