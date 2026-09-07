"""Sprint 16 Phase 7B.10/7B.11/7B.14 -- `prepare_approved_launch` orchestration.

Proves the orchestration layer immediately above Docker:

    job_id -> atomic PENDING claim -> VALIDATING
        -> reconstruct_launch_request() -> build_candidate()
        -> validate_and_approve() -> ApprovedLaunchSpec
        -> ExecutionAttempt(PENDING_CREATE) -> commit
        -> ApprovedLaunchPreparation

against REAL Postgres and a REAL resolved asset -- one function call this
time, instead of Phase 7B.9's manually-chained steps -- and that it:
  1. rejects an unknown job_id, with no claim attempted;
  2. rejects a job that cannot be claimed (Phase 7B.7 Part 10/12's
     idempotency concern), BEFORE any guard/resolver work runs;
  3. (Phase 7B.11) DOES mutate status on a successful claim -- PENDING ->
     VALIDATING -- superseding 7B.10's "never mutates status" claim, which
     was exactly the read-then-write gap this slice closes;
  4. leaves a claimed job at VALIDATING if guard/resolver validation
     fails afterward -- never auto-reverted to PENDING (that would let a
     `SecurityBlocked` loop into an automatic retry) and never advanced to
     FAILED (this slice does not invent that transition);
  5. a second preparation attempt on an already-claimed job cannot
     independently claim or prepare it;
  6. (Phase 7B.14) on success, returns an `ApprovedLaunchPreparation`
     (spec + attempt identity), not a bare `ApprovedLaunchSpec`;
  7. never launches anything -- no Docker, no Celery, no subprocess.

See test_execution_launch_claim.py for the dedicated, real-concurrency
proof of the claim primitive itself, and test_execution_attempt_creation.py
for the dedicated proof of attempt-creation behavior (naming, ordering,
failure semantics, concurrency at the orchestration boundary) -- this file
covers the orchestration layer's pre-existing (7B.10/7B.11) behavior,
updated only where the Phase 7B.14 return-type change requires it.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database.session import engine
from app.modules.assets.enums import AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.auth.models import User
from app.modules.execution.enums import ExecutionJobStatus
from app.modules.execution.models import ExecutionAttempt, ExecutionJob
from app.modules.execution.repository import ExecutionJobRepository
from app.modules.execution.schemas import ExecutionJobCreate
from app.modules.execution.service import (
    ApprovedLaunchPreparation,
    ExecutionJobNotEligibleError,
    ExecutionJobNotFoundError,
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
        email=f"pytest-orchestrate-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Orchestration Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_launch_orchestration.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Orchestration Test Project")
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


def _job_from_create(payload: ExecutionJobCreate, *, status: ExecutionJobStatus = ExecutionJobStatus.PENDING) -> ExecutionJob:
    data = payload.model_dump()
    data["input_asset_ids"] = [str(asset_id) for asset_id in payload.input_asset_ids]
    return ExecutionJob(status=status, **data)


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


# ---------------------------------------------------------------------------
# Happy path: one function call drives the full chain end to end.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_approved_launch_returns_a_real_approved_preparation(session, project):
    """Phase 7B.14: the return type changed from a bare `ApprovedLaunchSpec`
    to `ApprovedLaunchPreparation` (spec + attempt identity) -- see
    test_execution_attempt_creation.py for the dedicated attempt-shape
    coverage; this test only re-confirms the wrapped spec itself is still
    the same real, correct one."""
    storage_path = await _write_real_file(project, filename="orchestrated.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="orchestrated.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    preparation = await prepare_approved_launch(job.id, session)

    assert isinstance(preparation, ApprovedLaunchPreparation)
    approved = preparation.approved_spec
    assert isinstance(approved, ApprovedLaunchSpec)
    assert approved.job_id == job.id
    assert len(approved.mounts) == 1
    assert approved.mounts[0].destination == "/input/orchestrated.csv"


@pytest.mark.asyncio
async def test_prepare_approved_launch_claims_the_job_to_validating_on_success(session, project):
    """Phase 7B.11: supersedes 7B.10's "status never mutated" test -- a
    successful call now atomically claims the job first, so the row is
    `VALIDATING`, not `PENDING`, once `ApprovedLaunchSpec` comes back."""
    storage_path = await _write_real_file(project, filename="claimed.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="claimed.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    await prepare_approved_launch(job.id, session)

    refetched = await ExecutionJobRepository(session).get_by_id(job.id)
    assert refetched.status == ExecutionJobStatus.VALIDATING


@pytest.mark.asyncio
async def test_second_preparation_attempt_on_an_already_claimed_job_is_rejected(session, project):
    """Duplicate preparation (ORCHESTRATION TESTS item 5): the first call
    claims and succeeds; a second call for the same job -- e.g. a
    redelivered Celery message -- cannot independently claim or prepare
    it, even though the guard/resolver work of the first call already
    completed successfully."""
    storage_path = await _write_real_file(project, filename="duplicate.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="duplicate.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    first = await prepare_approved_launch(job.id, session)
    assert isinstance(first, ApprovedLaunchPreparation)

    with pytest.raises(ExecutionJobNotEligibleError) as exc_info:
        await prepare_approved_launch(job.id, session)
    assert exc_info.value.job_id == job.id
    assert exc_info.value.status == ExecutionJobStatus.VALIDATING

    refetched = await ExecutionJobRepository(session).get_by_id(job.id)
    assert refetched.status == ExecutionJobStatus.VALIDATING


# ---------------------------------------------------------------------------
# Unknown job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_job_id_raises_not_found(session):
    with pytest.raises(ExecutionJobNotFoundError):
        await prepare_approved_launch(uuid.uuid4(), session)


# ---------------------------------------------------------------------------
# Eligibility: only PENDING may proceed. Checked BEFORE any guard/resolver
# work -- proven by using an asset id that does not exist at all, so any
# resolver attempt would raise InputResolutionError instead.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        ExecutionJobStatus.VALIDATING,
        ExecutionJobStatus.LAUNCHING,
        ExecutionJobStatus.RUNNING,
        ExecutionJobStatus.SUCCEEDED,
        ExecutionJobStatus.FAILED,
        ExecutionJobStatus.TIMED_OUT,
        ExecutionJobStatus.CANCEL_REQUESTED,
        ExecutionJobStatus.CANCELLED,
    ],
)
async def test_non_pending_job_rejected_before_any_guard_work(session, project, status):
    payload = _matmul_create(project, input_asset_ids=[uuid.uuid4()])  # asset does not exist
    job = await ExecutionJobRepository(session).create(_job_from_create(payload, status=status))
    await session.commit()

    with pytest.raises(ExecutionJobNotEligibleError) as exc_info:
        await prepare_approved_launch(job.id, session)

    assert exc_info.value.job_id == job.id
    assert exc_info.value.status == status

    # The claim attempt (an UPDATE ... WHERE status = 'PENDING') matched
    # nothing for a job that was never PENDING -- status is unchanged.
    refetched = await ExecutionJobRepository(session).get_by_id(job.id)
    assert refetched.status == status


@pytest.mark.asyncio
async def test_pending_job_with_missing_asset_claims_then_fails_at_the_guard(session, project):
    """Sanity check on the ordering test above: a PENDING job with the
    same missing-asset shape DOES get claimed (VALIDATING) and DOES reach
    the resolver, failing there -- proving the eligibility check is what
    short-circuits the non-PENDING cases above, not something incidental
    about the missing asset. Also ORCHESTRATION TESTS item 4: the claim
    occurred, the guard rejected it, no ApprovedLaunchSpec was produced,
    and the job is left at VALIDATING (the chosen failure-state policy --
    see service.py's module docstring)."""
    payload = _matmul_create(project, input_asset_ids=[uuid.uuid4()])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    with pytest.raises(SecurityBlocked):
        await prepare_approved_launch(job.id, session)

    refetched = await ExecutionJobRepository(session).get_by_id(job.id)
    assert refetched.status == ExecutionJobStatus.VALIDATING

    # Phase 7B.14 item 4: a validation failure must create zero attempts.
    result = await session.execute(select(ExecutionAttempt).where(ExecutionAttempt.execution_job_id == job.id))
    assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# Guard rejections propagate unchanged; a claimed job is left VALIDATING,
# the chosen (smallest) failure-state policy -- not reverted to PENDING
# (no automatic retry of a SecurityBlocked result) and not advanced to
# FAILED (this slice does not invent that transition).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_rejection_propagates_and_leaves_job_claimed_at_validating(session, project):
    inconsistent = ExecutionJob(
        project_id=project.id,
        owner_id=project.owner_id,
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        capability=ExecutionCapability.EVALUATE_EXPRESSION,
        operation=ExecutionOperation.MATMUL,  # implies ARRAY_COMPUTE, not EVALUATE_EXPRESSION
        resource_class=ResourceClass.CLASS_ARRAY,
        parameters={},
        input_asset_ids=[],
        status=ExecutionJobStatus.PENDING,
    )
    job = await ExecutionJobRepository(session).create(inconsistent)
    await session.commit()

    with pytest.raises(SecurityBlocked):
        await prepare_approved_launch(job.id, session)

    # Claim occurred (PENDING -> VALIDATING committed by claim_pending_job
    # before the guard ever ran) and is NOT reverted by the subsequent
    # SecurityBlocked -- this is the documented, deliberate policy, not
    # an oversight: see service.py's module docstring "Failure policy".
    refetched = await ExecutionJobRepository(session).get_by_id(job.id)
    assert refetched.status == ExecutionJobStatus.VALIDATING

    result = await session.execute(select(ExecutionAttempt).where(ExecutionAttempt.execution_job_id == job.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_input_resolution_failure_propagates_unchanged(session, project):
    payload = _matmul_create(project, input_asset_ids=[uuid.uuid4()])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    with pytest.raises((SecurityBlocked, InputResolutionError)):
        await prepare_approved_launch(job.id, session)


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_prepare_approved_launch_is_async():
    assert inspect.iscoroutinefunction(prepare_approved_launch)


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


def test_docker_sdk_not_imported_at_runtime_by_execution_service_module():
    """AST-based (Sprint 16 Phase 7B.25 correction): a `sys.modules`
    check is no longer a valid proxy -- `execution_launcher.launcher`
    now legitimately imports the Docker SDK elsewhere in this codebase,
    and pytest runs the whole suite in one process, so
    `sys.modules["docker"]` can already be populated by an unrelated
    test file by the time this one runs. Checks `service.py`'s own
    source directly instead."""
    import pathlib

    import app.modules.execution.service as service_module

    source = pathlib.Path(service_module.__file__).read_text(encoding="utf-8")
    assert not _imports_any_of(source, {"docker"})
