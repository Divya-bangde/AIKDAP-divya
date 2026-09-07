"""Sprint 16 Phase 7B.9 -- `ExecutionJob` -> `LaunchRequest` reconstruction.

Proves the deterministic mapping in `app.modules.execution.service` is:
  1. field-complete (round-trips every `LaunchRequest` field from a real,
     persisted row, via a real Postgres round trip);
  2. usable by `build_candidate()`/`validate_and_approve()` DIRECTLY, no
     adapter -- the same live chain Phase 7B.5/7B.6 already proved, now
     fed from a reconstructed request instead of a hand-built one;
  3. free of authorization/consistency logic of its own (Rule 4) -- an
     internally-inconsistent row still reconstructs, and it is the GUARD,
     not the mapper, that rejects it.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.database.session import engine
from app.modules.assets.enums import AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.auth.models import User
from app.modules.execution.models import ExecutionJob
from app.modules.execution.repository import ExecutionJobRepository
from app.modules.execution.schemas import ExecutionJobCreate
from app.modules.execution.service import reconstruct_launch_request
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from execution_launcher.docker_policy import validate_and_approve
from execution_launcher.models import (
    ApprovedLaunchSpec,
    ExecutionCapability,
    ExecutionOperation,
    LaunchRequest,
    ResourceClass,
    SecurityBlocked,
)
from execution_launcher.resolvers import ProductionInputResolver
from execution_launcher.translator import build_candidate


# Same narrow, test-local workaround as test_execution_pre_docker_pipeline.py
# / test_execution_job_persistence.py for the repository's known
# module-level-engine + function-scoped-event-loop interaction. Does not
# touch app/database/session.py, conftest.py, or pytest.ini.
@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_between_tests():
    await engine.dispose()
    yield


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-reconstruct-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Reconstruction Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_job_reconstruction.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Reconstruction Test Project")
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


def _job_from_create(payload: ExecutionJobCreate) -> ExecutionJob:
    data = payload.model_dump()
    data["input_asset_ids"] = [str(asset_id) for asset_id in payload.input_asset_ids]
    return ExecutionJob(**data)


def _matmul_create(project: Project, *, input_asset_ids: list[uuid.UUID]) -> ExecutionJobCreate:
    return ExecutionJobCreate(
        project_id=project.id,
        owner_id=project.owner_id,
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        capability=ExecutionCapability.ARRAY_COMPUTE,
        operation=ExecutionOperation.MATMUL,
        resource_class=ResourceClass.CLASS_ARRAY,
        parameters={"note": "reconstruction test"},
        input_asset_ids=input_asset_ids,
    )


# ---------------------------------------------------------------------------
# Field-complete round trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconstruct_launch_request_round_trips_all_fields(session, project):
    asset_ids = [uuid.uuid4(), uuid.uuid4()]
    payload = _matmul_create(project, input_asset_ids=asset_ids)
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    fetched = await ExecutionJobRepository(session).get_by_id(job.id)
    request = reconstruct_launch_request(fetched)

    assert isinstance(request, LaunchRequest)
    assert request.job_id == job.id
    assert request.experiment_plan_id == payload.experiment_plan_id
    assert request.experiment_plan_version == 1
    assert request.owner_id == project.owner_id
    assert request.project_id == project.id
    assert request.capability == ExecutionCapability.ARRAY_COMPUTE
    assert request.operation == ExecutionOperation.MATMUL
    assert request.parameters == {"note": "reconstruction test"}
    assert request.resource_class == ResourceClass.CLASS_ARRAY
    assert request.input_asset_ids == asset_ids


@pytest.mark.asyncio
async def test_reconstructed_request_is_a_frozen_launch_request(session, project):
    job = await ExecutionJobRepository(session).create(
        _job_from_create(_matmul_create(project, input_asset_ids=[]))
    )
    await session.commit()

    request = reconstruct_launch_request(job)
    with pytest.raises(Exception):
        request.operation = ExecutionOperation.EVALUATE_EXPRESSION  # type: ignore[misc]


def test_reconstruct_launch_request_takes_only_the_job_no_session_or_io():
    """Structural: the mapper's only parameter is the row itself -- no
    session, no repository, nothing that would let it perform its own
    I/O or authorization (Rule 4)."""
    params = list(inspect.signature(reconstruct_launch_request).parameters)
    assert params == ["job"]
    assert not inspect.iscoroutinefunction(reconstruct_launch_request)


# ---------------------------------------------------------------------------
# Drives build_candidate()/validate_and_approve() DIRECTLY -- no adapter,
# no duplicate mapping layer. Same live chain as Phase 7B.5/7B.6, now fed
# from a reconstructed request.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconstructed_request_drives_the_full_guard_pipeline_directly(session, project):
    storage_path = await _write_real_file(project, filename="reconstructed.csv")
    asset = await _make_asset(session, project, storage_path=storage_path, file_name="reconstructed.csv")
    await session.commit()

    payload = _matmul_create(project, input_asset_ids=[asset.id])
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    # The exact future shape: job_id -> get_by_id() -> reconstruct ->
    # fresh resolver -> build_candidate() -> validate_and_approve().
    fetched = await ExecutionJobRepository(session).get_by_id(job.id)
    request = reconstruct_launch_request(fetched)
    resolver = ProductionInputResolver(session)

    candidate = await build_candidate(request, resolver)
    assert candidate.request.job_id == job.id
    assert len(candidate.mounts) == 1
    assert candidate.mounts[0].destination == "/input/reconstructed.csv"

    approved = await validate_and_approve(candidate, resolver)
    assert isinstance(approved, ApprovedLaunchSpec)
    assert approved.job_id == job.id


# ---------------------------------------------------------------------------
# Rule 4: the mapper does not validate -- an internally-inconsistent row
# still reconstructs; the GUARD is what rejects it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mapper_does_not_reject_inconsistent_capability_operation_the_guard_does(session, project):
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
    )
    job = await ExecutionJobRepository(session).create(inconsistent)
    await session.commit()

    # The mapper itself raises nothing -- it is pure field mapping.
    request = reconstruct_launch_request(job)
    assert request.capability == ExecutionCapability.EVALUATE_EXPRESSION
    assert request.operation == ExecutionOperation.MATMUL

    # The guard is what catches it, exactly as it would for a hand-built
    # inconsistent LaunchRequest -- no special-casing for reconstructed ones.
    resolver = ProductionInputResolver(session)
    with pytest.raises(SecurityBlocked):
        await build_candidate(request, resolver)


# ---------------------------------------------------------------------------
# Structural: Rules 1/2/3 compliance for the new mapping module.
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
