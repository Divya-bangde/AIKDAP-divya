"""Sprint 16 Phase 7B.11 -- `ExecutionJobRepository.claim_pending_job()`.

Proves the atomic `PENDING -> VALIDATING` claim: a single conditional
`UPDATE ... WHERE status = 'PENDING' RETURNING *` against REAL Postgres,
not a read-then-write gap in Python. This is the closure of the race
Phase 7B.7 identified as unresolved ("two launchers both read PENDING,
both prepare an ApprovedLaunchSpec"):

  1. two genuinely concurrent claim attempts against the same row --
     exactly one succeeds, the other observes the row is no longer
     claimable (never both -- the database decides, not application code);
  2. a second, sequential claim attempt after a successful one cannot
     re-claim it (duplicate Celery delivery / duplicate launcher attempt);
  3. every other status in the lifecycle rejects a claim attempt.

Does not touch Docker, Celery, or anything execution-shaped -- this file
tests one repository method in isolation from the orchestration layer
(see test_execution_launch_orchestration.py for the integrated behavior).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.database.session import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.execution.enums import ExecutionJobStatus
from app.modules.execution.models import ExecutionJob
from app.modules.execution.repository import ExecutionJobRepository
from app.modules.execution.schemas import ExecutionJobCreate
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from execution_launcher.models import ExecutionCapability, ExecutionOperation, ResourceClass


# Same narrow, test-local workaround as the other execution_* test files
# for the repository's known module-level-engine + function-scoped-
# event-loop interaction. Does not touch app/database/session.py,
# conftest.py, or pytest.ini.
@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_between_tests():
    await engine.dispose()
    yield


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-claim-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Claim Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_launch_claim.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Claim Test Project")
    yield proj
    user = await session.get(User, proj.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


def _matmul_create(project: Project) -> ExecutionJobCreate:
    return ExecutionJobCreate(
        project_id=project.id,
        owner_id=project.owner_id,
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        capability=ExecutionCapability.ARRAY_COMPUTE,
        operation=ExecutionOperation.MATMUL,
        resource_class=ResourceClass.CLASS_ARRAY,
        parameters={},
        input_asset_ids=[],
    )


def _job_from_create(payload: ExecutionJobCreate, *, status: ExecutionJobStatus = ExecutionJobStatus.PENDING) -> ExecutionJob:
    data = payload.model_dump()
    data["input_asset_ids"] = [str(asset_id) for asset_id in payload.input_asset_ids]
    return ExecutionJob(status=status, **data)


# ---------------------------------------------------------------------------
# Concurrency: the central claim this slice exists to prove. Two genuinely
# concurrent attempts (asyncio.gather, two independent sessions/connections
# against real Postgres) -- not two sequential calls.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_claims_exactly_one_succeeds(session, project):
    job = await ExecutionJobRepository(session).create(_job_from_create(_matmul_create(project)))
    await session.commit()
    job_id = job.id

    async def _attempt() -> ExecutionJob | None:
        async with async_session_factory() as attempt_session:
            return await ExecutionJobRepository(attempt_session).claim_pending_job(job_id)

    result_a, result_b = await asyncio.gather(_attempt(), _attempt())

    results = [result_a, result_b]
    successes = [r for r in results if r is not None]
    rejections = [r for r in results if r is None]

    assert len(successes) == 1, f"expected exactly 1 success, got {len(successes)}"
    assert len(rejections) == 1, f"expected exactly 1 rejection, got {len(rejections)}"
    assert successes[0].id == job_id
    assert successes[0].status == ExecutionJobStatus.VALIDATING

    async with async_session_factory() as verify_session:
        final = await ExecutionJobRepository(verify_session).get_by_id(job_id)
    assert final.status == ExecutionJobStatus.VALIDATING


@pytest.mark.asyncio
async def test_three_concurrent_claims_exactly_one_succeeds(session, project):
    """Same invariant with a third contender, to rule out a 2-caller-only
    coincidence (e.g. a race that happens to resolve cleanly only when
    exactly two attempts are in flight)."""
    job = await ExecutionJobRepository(session).create(_job_from_create(_matmul_create(project)))
    await session.commit()
    job_id = job.id

    async def _attempt() -> ExecutionJob | None:
        async with async_session_factory() as attempt_session:
            return await ExecutionJobRepository(attempt_session).claim_pending_job(job_id)

    results = await asyncio.gather(_attempt(), _attempt(), _attempt())

    successes = [r for r in results if r is not None]
    rejections = [r for r in results if r is None]
    assert len(successes) == 1
    assert len(rejections) == 2


# ---------------------------------------------------------------------------
# Duplicate delivery: sequential, not concurrent -- a redelivered Celery
# message arriving after the first claim already committed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_claim_after_success_is_rejected(session, project):
    job = await ExecutionJobRepository(session).create(_job_from_create(_matmul_create(project)))
    await session.commit()

    first = await ExecutionJobRepository(session).claim_pending_job(job.id)
    assert first is not None
    assert first.status == ExecutionJobStatus.VALIDATING

    second = await ExecutionJobRepository(session).claim_pending_job(job.id)
    assert second is None

    refetched = await ExecutionJobRepository(session).get_by_id(job.id)
    assert refetched.status == ExecutionJobStatus.VALIDATING


@pytest.mark.asyncio
async def test_claiming_a_nonexistent_job_returns_none_not_an_exception(session):
    result = await ExecutionJobRepository(session).claim_pending_job(uuid.uuid4())
    assert result is None


# ---------------------------------------------------------------------------
# Status matrix: only PENDING is claimable. Every other status in the
# lifecycle -- including ones no code path produces yet -- must reject.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,claim_allowed",
    [
        (ExecutionJobStatus.PENDING, True),
        (ExecutionJobStatus.VALIDATING, False),
        (ExecutionJobStatus.LAUNCHING, False),
        (ExecutionJobStatus.RUNNING, False),
        (ExecutionJobStatus.SUCCEEDED, False),
        (ExecutionJobStatus.FAILED, False),
        (ExecutionJobStatus.TIMED_OUT, False),
        (ExecutionJobStatus.CANCEL_REQUESTED, False),
        (ExecutionJobStatus.CANCELLED, False),
    ],
)
async def test_claim_status_matrix(session, project, status, claim_allowed):
    job = await ExecutionJobRepository(session).create(
        _job_from_create(_matmul_create(project), status=status)
    )
    await session.commit()

    result = await ExecutionJobRepository(session).claim_pending_job(job.id)

    if claim_allowed:
        assert result is not None
        assert result.status == ExecutionJobStatus.VALIDATING
    else:
        assert result is None
        refetched = await ExecutionJobRepository(session).get_by_id(job.id)
        assert refetched.status == status


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def _imports_any_of(source: str, module_names: set[str]) -> bool:
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in module_names for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in module_names:
                return True
    return False


def test_execution_repository_module_never_imports_docker_celery_or_subprocess():
    import pathlib

    import app.modules.execution.repository as repository_module

    source = pathlib.Path(repository_module.__file__).read_text(encoding="utf-8")
    assert not _imports_any_of(source, {"docker", "celery", "subprocess"})


def test_docker_sdk_not_imported_at_runtime_by_execution_repository_module():
    """AST-based (Sprint 16 Phase 7B.25 correction): a `sys.modules`
    check is no longer a valid proxy -- `execution_launcher.launcher`
    now legitimately imports the Docker SDK elsewhere in this codebase,
    and pytest runs the whole suite in one process, so
    `sys.modules["docker"]` can already be populated by an unrelated
    test file by the time this one runs. Checks `repository.py`'s own
    source directly instead."""
    import pathlib

    import app.modules.execution.repository as repository_module

    source = pathlib.Path(repository_module.__file__).read_text(encoding="utf-8")
    assert not _imports_any_of(source, {"docker"})
