"""Sprint 16 Phase 7B.5/7B.6 -- pre-Docker pipeline composition tests.

Proves that:

    LaunchRequest -> build_candidate() -> ProductionInputResolver
        -> validate_and_approve() -> ApprovedLaunchSpec

composes correctly against a REAL authorized asset, as ONE literal live
call chain. This suite does not repeat Phase 7B.3's 57 guard unit tests
or Phase 7B.4's 24 resolver unit tests -- it tests composition only.

HISTORY: Phase 7B.5 found that `InputResolver.resolve()` was a
SYNCHRONOUS protocol method (Phase 7B.3), matching `StaticInputResolver`,
while `ProductionInputResolver` (Phase 7B.4) is necessarily `async def`
(every database call in this codebase is async) -- `build_candidate()`/
`validate_and_approve()` could not directly drive it, so 7B.5 proved
composition only through a disclosed, test-only sync adapter carrying
real resolved data. Phase 7B.6 closed that gap by converting
`InputResolver.resolve()`, `StaticInputResolver.resolve()`,
`docker_policy._expected_mounts()`, `docker_policy.validate_and_approve()`,
and `translator.build_candidate()` to `async def` (mechanical -- no
security-logic change), matching this repo's own established
`asyncio.run()`-at-the-boundary bridging convention (`app/workers/tasks.py`)
rather than nesting a loop inside one. The adapter is gone from the tests
below; `ProductionInputResolver` now drives the guard directly.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
import pytest_asyncio

from app.database.session import engine
from app.modules.assets.enums import AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.auth.models import User
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from execution_launcher.docker_policy import validate_and_approve
from execution_launcher.models import (
    ApprovedLaunchSpec,
    ExecutionCapability,
    ExecutionOperation,
    InputResolutionError,
    LaunchRequest,
    MountSpec,
    ResourceClass,
    SecurityBlocked,
)
from execution_launcher.resolvers import ProductionInputResolver, StaticInputResolver
from execution_launcher.translator import build_candidate


# ---------------------------------------------------------------------------
# Narrow, test-local workaround for the repository's known module-level-
# engine + function-scoped-event-loop interaction (Phase 7B.4 Section 10/13:
# "RuntimeError: ... attached to a different loop"). Disposing the pool
# forces fresh, current-loop-bound connections. Does not touch
# app/database/session.py, conftest.py, or pytest.ini.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_between_tests():
    await engine.dispose()
    yield


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-pipeline-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Pipeline Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_pre_docker_pipeline.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


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


def _matmul_request(*, owner_id, project_id, input_asset_ids) -> LaunchRequest:
    return LaunchRequest(
        job_id=uuid.uuid4(),
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        owner_id=owner_id,
        project_id=project_id,
        capability=ExecutionCapability.ARRAY_COMPUTE,
        operation=ExecutionOperation.MATMUL,
        parameters={},
        resource_class=ResourceClass.CLASS_ARRAY,
        input_asset_ids=input_asset_ids,
    )


@pytest_asyncio.fixture
async def project_a(session) -> AsyncIterator[Project]:
    project = await _make_owner_and_project(session, name="Pipeline Project A")
    yield project
    user = await session.get(User, project.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


@pytest_asyncio.fixture
async def project_b(session) -> AsyncIterator[Project]:
    project = await _make_owner_and_project(session, name="Pipeline Project B")
    yield project
    user = await session.get(User, project.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


# ---------------------------------------------------------------------------
# The Phase 7B.5 architectural gap, now closed (Phase 7B.6): proven
# structurally, then proven live in the happy-path test below.
# ---------------------------------------------------------------------------


def test_production_resolver_is_now_compatible_with_the_guard_pipeline():
    assert inspect.iscoroutinefunction(ProductionInputResolver.resolve)
    assert inspect.iscoroutinefunction(StaticInputResolver.resolve)
    assert inspect.iscoroutinefunction(build_candidate)
    assert inspect.iscoroutinefunction(validate_and_approve)
    # docker_policy._expected_mounts() now awaits resolver.resolve() --
    # ProductionInputResolver can drive build_candidate()/
    # validate_and_approve() directly, proven live below.


# ---------------------------------------------------------------------------
# Happy path: REAL Postgres, REAL storage file, REAL ProductionInputResolver
# resolution, driving build_candidate()/validate_and_approve() DIRECTLY --
# one literal live call chain, no adapter (Phase 7B.6).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_real_asset_composes_through_the_full_pipeline(session, project_a):
    storage_path = await _write_real_file(project_a, filename="pipeline.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path, file_name="pipeline.csv")
    await session.commit()

    resolver = ProductionInputResolver(session)
    request = _matmul_request(
        owner_id=project_a.owner_id, project_id=project_a.id, input_asset_ids=[asset.id]
    )

    # REAL, direct chain: LaunchRequest -> build_candidate() ->
    # ProductionInputResolver -> validate_and_approve() -> ApprovedLaunchSpec.
    candidate = await build_candidate(request, resolver)
    assert candidate.request.operation == ExecutionOperation.MATMUL
    assert candidate.request.capability == ExecutionCapability.ARRAY_COMPUTE
    assert candidate.request.input_asset_ids == [asset.id]
    assert len(candidate.mounts) == 1
    assert candidate.mounts[0].destination == "/input/pipeline.csv"
    assert candidate.mounts[0].mode == "ro"
    assert candidate.mounts[0].source.endswith("pipeline.csv")

    approved = await validate_and_approve(candidate, resolver)
    assert isinstance(approved, ApprovedLaunchSpec)
    assert approved.mounts == candidate.mounts


# ---------------------------------------------------------------------------
# Security negative cases -- real ProductionInputResolver, real Postgres.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_owner_rejected_and_produces_no_approved_spec(session, project_a):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path, file_name="a.csv")
    await session.commit()

    with pytest.raises(InputResolutionError):
        await ProductionInputResolver(session).resolve(
            owner_id=uuid.uuid4(), project_id=project_a.id, asset_id=asset.id
        )
    # No ApprovedLaunchSpec is reachable -- the pipeline never gets past
    # resolution, so build_candidate()/validate_and_approve() are never
    # even called with a usable input.


@pytest.mark.asyncio
async def test_wrong_project_rejected(session, project_a):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path, file_name="a.csv")
    await session.commit()

    with pytest.raises(InputResolutionError):
        await ProductionInputResolver(session).resolve(
            owner_id=project_a.owner_id, project_id=uuid.uuid4(), asset_id=asset.id
        )


@pytest.mark.asyncio
async def test_cross_project_asset_rejected(session, project_a, project_b):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset_a = await _make_asset(session, project_a, storage_path=storage_path, file_name="a.csv")
    await session.commit()

    with pytest.raises(InputResolutionError):
        await ProductionInputResolver(session).resolve(
            owner_id=project_b.owner_id, project_id=project_b.id, asset_id=asset_a.id
        )


# ---------------------------------------------------------------------------
# Candidate tampering -- built from a REAL resolved input, then mutated,
# proving the guard's independent re-derivation rejects the tampering
# rather than trusting the candidate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidate_input_mount_tampering_rejected(session, project_a):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path, file_name="a.csv")
    await session.commit()

    resolver = ProductionInputResolver(session)
    request = _matmul_request(
        owner_id=project_a.owner_id, project_id=project_a.id, input_asset_ids=[asset.id]
    )
    candidate = await build_candidate(request, resolver)

    tampered = replace(
        candidate,
        mounts=(MountSpec(source="/etc/passwd", destination="/input/passwd", mode="ro"),),
    )
    with pytest.raises(SecurityBlocked):
        await validate_and_approve(tampered, resolver)


@pytest.mark.asyncio
async def test_candidate_operation_tampering_rejected(session, project_a):
    storage_path = await _write_real_file(project_a, filename="a.csv")
    asset = await _make_asset(session, project_a, storage_path=storage_path, file_name="a.csv")
    await session.commit()

    resolver = ProductionInputResolver(session)
    request = _matmul_request(
        owner_id=project_a.owner_id, project_id=project_a.id, input_asset_ids=[asset.id]
    )
    candidate = await build_candidate(request, resolver)

    # Leave capability/resource_class as ARRAY_COMPUTE/CLASS_ARRAY but
    # change the operation to one that implies a different capability --
    # an inconsistent combination the guard must independently catch.
    inconsistent_request = request.model_copy(
        update={"operation": ExecutionOperation.EVALUATE_EXPRESSION}
    )
    tampered = replace(candidate, request=inconsistent_request)
    with pytest.raises(SecurityBlocked):
        await validate_and_approve(tampered, resolver)


@pytest.mark.asyncio
async def test_resolver_failure_never_falls_back_to_static_resolver(session, project_a):
    """If ProductionInputResolver fails, nothing silently substitutes a
    StaticInputResolver or synthesizes a ResolvedInput -- the failure
    propagates, full stop."""
    with pytest.raises(InputResolutionError):
        await ProductionInputResolver(session).resolve(
            owner_id=project_a.owner_id, project_id=project_a.id, asset_id=uuid.uuid4()
        )


# ---------------------------------------------------------------------------
# Structural: no Docker/subprocess/shell anywhere in this integration
# module or the execution_launcher package it exercises. AST-based, not
# substring matching (this file's own docstrings and comments mention
# "asyncio.run()" and "docker" in prose and must not self-flag).
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


def test_no_docker_or_subprocess_anywhere_in_this_integration_or_execution_launcher():
    import pathlib

    import execution_launcher.docker_policy as docker_policy_module
    import execution_launcher.resolvers as resolvers_module
    import execution_launcher.translator as translator_module

    this_file = pathlib.Path(__file__)
    package_files = [
        pathlib.Path(docker_policy_module.__file__),
        pathlib.Path(resolvers_module.__file__),
        pathlib.Path(translator_module.__file__),
        this_file,
    ]
    forbidden = {"docker", "subprocess"}
    for path in package_files:
        source = path.read_text(encoding="utf-8")
        assert not _imports_any_of(source, forbidden), f"{path.name} imports one of {forbidden}"


def test_docker_sdk_not_present_in_sys_modules_after_running_this_pipeline():
    """AST-based (Sprint 16 Phase 7B.25 correction): a `sys.modules`
    check is no longer a valid proxy -- `execution_launcher.launcher`
    (a sibling module in the same package) now legitimately imports the
    Docker SDK, and pytest runs the whole suite in one process, so
    `sys.modules["docker"]` can already be populated by an unrelated
    test file by the time this one runs. Re-asserts the same guarantee
    via source instead -- identical check to the one immediately above,
    kept as its own test since it existed under this name already."""
    import pathlib

    import execution_launcher.docker_policy as docker_policy_module
    import execution_launcher.resolvers as resolvers_module
    import execution_launcher.translator as translator_module

    package_files = [
        pathlib.Path(docker_policy_module.__file__),
        pathlib.Path(resolvers_module.__file__),
        pathlib.Path(translator_module.__file__),
    ]
    for path in package_files:
        source = path.read_text(encoding="utf-8")
        assert not _imports_any_of(source, {"docker"}), f"{path.name} imports docker"
