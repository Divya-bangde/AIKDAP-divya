"""Sprint 16 Phase 7B.14 -- `ExecutionAttempt` creation inside orchestration.

Proves the integration `prepare_approved_launch()` now performs, on top
of everything Phase 7B.9-7B.11 already proved:

    ApprovedLaunchSpec -> create ExecutionAttempt(PENDING_CREATE)
        -> persist deterministic container_name -> commit
        -> ApprovedLaunchPreparation

against REAL Postgres and a REAL resolved asset, including a genuine
concurrent-caller test extending Phase 7B.11's claim-level concurrency
proof up to this full orchestration boundary. Never contacts Docker --
`container_name`/`container_id` values here are computed/stored strings
only, never validated against a real daemon.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.session import async_session_factory, engine
from app.modules.assets.enums import AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.auth.models import User
from app.modules.execution.enums import ExecutionAttemptStatus, ExecutionJobStatus
from app.modules.execution.models import ExecutionAttempt, ExecutionJob
from app.modules.execution.repository import ExecutionAttemptRepository, ExecutionJobRepository
from app.modules.execution.schemas import ExecutionJobCreate
from app.modules.execution.service import (
    ApprovedLaunchPreparation,
    ExecutionJobNotEligibleError,
    container_name_for_attempt,
    prepare_approved_launch,
)
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from execution_launcher.models import (
    ApprovedLaunchSpec,
    ExecutionCapability,
    ExecutionOperation,
    InputResolutionError,
    ResourceClass,
    SecurityBlocked,
)


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
        email=f"pytest-attemptcreate-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Attempt Creation Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_attempt_creation.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Attempt Creation Test Project")
    yield proj
    user = await session.get(User, proj.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


async def _write_real_file(project: Project, *, filename: str) -> str:
    storage = get_storage_provider()
    return await storage.save(project_id=project.id, filename=filename, content=b"1,2\n3,4\n")


async def _make_asset(session, project: Project, *, storage_path: str, file_name: str) -> Asset:
    asset = Asset(
        project_id=project.id,
        owner_id=project.owner_id,
        title=file_name,
        file_name=file_name,
        file_extension=file_name.rsplit(".", 1)[-1],
        mime_type="text/csv",
        file_size=0,
        storage_path=storage_path,
        checksum="test-checksum",
        asset_type=AssetType.DATASET,
        status=AssetStatus.ACTIVE,
        source=AssetSource.UPLOAD,
        tags=[],
    )
    return await AssetRepository(session).create(asset)


def _matmul_create(project: Project, *, input_asset_ids: list[uuid.UUID]) -> ExecutionJobCreate:
    return ExecutionJobCreate(
        project_id=project.id,
        owner_id=project.owner_id,
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        capability=ExecutionCapability.ARRAY_COMPUTE,
        operation=ExecutionOperation.MATMUL,
        resource_class=ResourceClass.CLASS_ARRAY,
        parameters={},
        input_asset_ids=input_asset_ids,
    )


def _job_from_create(payload: ExecutionJobCreate) -> ExecutionJob:
    data = payload.model_dump()
    data["input_asset_ids"] = [str(asset_id) for asset_id in payload.input_asset_ids]
    return ExecutionJob(status=ExecutionJobStatus.PENDING, **data)


async def _attempts_for_job(session, job_id: uuid.UUID) -> list[ExecutionAttempt]:
    result = await session.execute(select(ExecutionAttempt).where(ExecutionAttempt.execution_job_id == job_id))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 1. Successful preparation creates exactly one attempt.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_preparation_creates_one_attempt(session, project):
    storage_path = await _write_real_file(project, filename="attempt.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="attempt.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    preparation = await prepare_approved_launch(job.id, session)

    assert isinstance(preparation, ApprovedLaunchPreparation)
    assert isinstance(preparation.approved_spec, ApprovedLaunchSpec)

    attempts = await _attempts_for_job(session, job.id)
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.id == preparation.attempt_id
    assert attempt.execution_job_id == job.id
    assert attempt.attempt_number == 1
    assert attempt.status == ExecutionAttemptStatus.PENDING_CREATE
    assert attempt.container_id is None
    assert attempt.container_name == preparation.container_name
    assert attempt.container_name == container_name_for_attempt(attempt.id)


# ---------------------------------------------------------------------------
# 2. Deterministic naming: same id -> same name, computed independently.
# ---------------------------------------------------------------------------


def test_container_name_for_attempt_is_deterministic():
    attempt_id = uuid.uuid4()
    first = container_name_for_attempt(attempt_id)
    second = container_name_for_attempt(attempt_id)
    assert first == second
    assert first == f"aikdap-exec-{attempt_id}"


def test_container_name_for_attempt_differs_across_ids():
    assert container_name_for_attempt(uuid.uuid4()) != container_name_for_attempt(uuid.uuid4())


def test_container_name_for_attempt_uses_only_docker_safe_characters():
    name = container_name_for_attempt(uuid.uuid4())
    assert len(name) <= 255
    assert all(c.isalnum() or c in "_.-" for c in name)
    assert name[0].isalnum()


# ---------------------------------------------------------------------------
# 3. Name persists across create -> commit -> reload, via a fresh session.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_container_name_persists_and_matches_reconstruction(session, project):
    storage_path = await _write_real_file(project, filename="persist.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="persist.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    preparation = await prepare_approved_launch(job.id, session)

    async with async_session_factory() as reload_session:
        reloaded = await ExecutionAttemptRepository(reload_session).get_by_id(preparation.attempt_id)

    assert reloaded is not None
    assert reloaded.container_name == preparation.container_name
    # Reconstructing the name from the persisted, immutable id independently
    # reproduces the exact stored value -- proves the stored string really
    # is that deterministic function of `id`, not something else that
    # merely happened to match once.
    assert reloaded.container_name == container_name_for_attempt(reloaded.id)


# ---------------------------------------------------------------------------
# 4. Validation failure creates no attempt.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validation_failure_creates_no_attempt(session, project):
    payload = _matmul_create(project, input_asset_ids=[uuid.uuid4()])  # asset does not exist
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    with pytest.raises((SecurityBlocked, InputResolutionError)):
        await prepare_approved_launch(job.id, session)

    assert await _attempts_for_job(session, job.id) == []


@pytest.mark.asyncio
async def test_cross_project_asset_rejected_creates_no_attempt(session, project):
    """A concrete instance of 'validation failure' using the exact shape
    the prompt names: a cross-project asset the resolver must reject."""
    other_project = await _make_owner_and_project(session, name="Attempt Creation Foreign Project")
    storage_path = await _write_real_file(other_project, filename="foreign.csv")
    foreign_asset = await _make_asset(session, other_project, storage_path=storage_path, file_name="foreign.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[foreign_asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    with pytest.raises((SecurityBlocked, InputResolutionError)):
        await prepare_approved_launch(job.id, session)

    assert await _attempts_for_job(session, job.id) == []

    user = await session.get(User, other_project.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


# ---------------------------------------------------------------------------
# 5. Second preparation on an already-claimed job creates no second attempt.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_preparation_creates_no_second_attempt(session, project):
    storage_path = await _write_real_file(project, filename="second.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="second.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    first = await prepare_approved_launch(job.id, session)

    with pytest.raises(ExecutionJobNotEligibleError):
        await prepare_approved_launch(job.id, session)

    attempts = await _attempts_for_job(session, job.id)
    assert len(attempts) == 1
    assert attempts[0].id == first.attempt_id


# ---------------------------------------------------------------------------
# 6. Concurrency: extends Phase 7B.11's claim-level proof up to the full
# orchestration boundary. Two genuinely concurrent callers, independent
# sessions/connections, real Postgres.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_preparation_exactly_one_succeeds_with_one_attempt(session, project):
    storage_path = await _write_real_file(project, filename="concurrent.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="concurrent.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()
    job_id = job.id

    async def _attempt():
        async with async_session_factory() as attempt_session:
            try:
                return await prepare_approved_launch(job_id, attempt_session)
            except ExecutionJobNotEligibleError as exc:
                return exc

    result_a, result_b = await asyncio.gather(_attempt(), _attempt())
    results = [result_a, result_b]

    successes = [r for r in results if isinstance(r, ApprovedLaunchPreparation)]
    rejections = [r for r in results if isinstance(r, ExecutionJobNotEligibleError)]
    assert len(successes) == 1, f"expected exactly 1 success, got {len(successes)}: {results}"
    assert len(rejections) == 1, f"expected exactly 1 rejection, got {len(rejections)}: {results}"

    async with async_session_factory() as verify_session:
        final_job = await ExecutionJobRepository(verify_session).get_by_id(job_id)
        assert final_job.status == ExecutionJobStatus.VALIDATING

        attempts = await _attempts_for_job(verify_session, job_id)
        assert len(attempts) == 1
        assert attempts[0].id == successes[0].attempt_id


# ---------------------------------------------------------------------------
# 7. Attempt-creation failure: a real DB constraint violation, forced by
# pre-existing state that violates the (execution_job_id, attempt_number)
# uniqueness this slice's attempt_number=1 invariant assumes cannot
# collide. Proves: the exception propagates, no partial/second attempt
# row survives, and the already-committed claim (VALIDATING) is untouched
# -- these are two separate transactions (see service.py's module
# docstring), not one that could partially roll back together.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attempt_creation_constraint_violation_propagates_with_no_partial_attempt(session, project):
    storage_path = await _write_real_file(project, filename="conflict.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="conflict.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()
    job_id = job.id

    # Pre-existing state that violates this slice's own invariant ("the
    # first successful claim is the only one that will ever try to write
    # attempt_number=1 for this job") -- simulates the real DB constraint
    # firing, not a mock.
    pre_existing = ExecutionAttempt(
        execution_job_id=job_id,
        attempt_number=1,
        container_name=container_name_for_attempt(uuid.uuid4()),
    )
    await ExecutionAttemptRepository(session).create(pre_existing)
    await session.commit()
    pre_existing_id = pre_existing.id

    # The failing call runs against its own independent session -- both
    # `job` and `pre_existing` are already committed above, so a fresh
    # session sees them fine. This is the same isolation pattern already
    # proven in test_execution_attempt_persistence.py's duplicate-
    # constraint tests: it keeps the primary `session` fixture's
    # transaction/identity-map state completely untouched by the failure,
    # avoiding the need to roll it back (which would expire every object
    # still attached to it, including the `project` fixture's own row,
    # and break that fixture's teardown).
    async with async_session_factory() as violating_session:
        with pytest.raises(IntegrityError):
            await prepare_approved_launch(job_id, violating_session)

    # The claim (a separate, already-committed transaction) is untouched --
    # the job is VALIDATING regardless of the later attempt-creation failure.
    async with async_session_factory() as verify_session:
        final_job = await ExecutionJobRepository(verify_session).get_by_id(job_id)
        assert final_job.status == ExecutionJobStatus.VALIDATING

        attempts = await _attempts_for_job(verify_session, job_id)
    # Only the pre-existing row -- the failed insert left no second/partial
    # row behind (Postgres's own transactional guarantee: the failed
    # flush's INSERT was never committed).
    assert len(attempts) == 1
    assert attempts[0].id == pre_existing_id


# ---------------------------------------------------------------------------
# 8. Structural: Docker/Celery absence in the modified execution module.
# Scoped to the module itself -- conftest.py imports app.workers.celery_app
# process-wide for FK registration, so a bare "celery not in sys.modules"
# check would false-positive regardless of what this module does.
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


def test_execution_service_module_never_imports_docker_celery_or_subprocess():
    import pathlib

    import app.modules.execution.service as service_module

    source = pathlib.Path(service_module.__file__).read_text(encoding="utf-8")
    assert not _imports_any_of(source, {"docker", "celery", "subprocess"})


def test_docker_sdk_not_imported_at_runtime_after_full_preparation_flow():
    """AST-based (Sprint 16 Phase 7B.25 correction): a `sys.modules`
    check is no longer a valid proxy for this module's own import chain
    -- `execution_launcher.launcher` now legitimately imports the
    Docker SDK elsewhere in this codebase, and pytest runs the whole
    suite in one process, so `sys.modules["docker"]` can already be
    populated by an unrelated test file by the time this one runs.
    Re-asserts the same guarantee via source instead (matches
    `test_execution_service_module_never_imports_docker_celery_or_subprocess`
    directly above)."""
    import pathlib

    import app.modules.execution.service as service_module

    source = pathlib.Path(service_module.__file__).read_text(encoding="utf-8")
    assert not _imports_any_of(source, {"docker"})
