"""Sprint 16 Phase 7B.8 -- `ExecutionJob` persistence tests.

Real database (via the `session` fixture already used throughout this
suite) -- no mocks for persistence itself. Proves the row round-trips
through `ExecutionJobRepository`/`ExecutionJobRead` with the exact shape
a future launcher's `job_id -> authoritative persisted execution state`
lookup (Phase 7B.7 Part 4/6) will depend on, and that Rules 1/2/3 (no
Docker, no Celery task, no execution) hold structurally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.database.session import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.execution.enums import ExecutionJobStatus
from app.modules.execution.models import ExecutionJob
from app.modules.execution.repository import ExecutionJobRepository
from app.modules.execution.schemas import ExecutionJobCreate, ExecutionJobRead
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from execution_launcher.models import ExecutionCapability, ExecutionOperation, ResourceClass


# Same narrow, test-local workaround as test_execution_pre_docker_pipeline.py
# (Phase 7B.5/7B.6) for the repository's known module-level-engine +
# function-scoped-event-loop interaction. Does not touch
# app/database/session.py, conftest.py, or pytest.ini.
@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_between_tests():
    await engine.dispose()
    yield


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-execjob-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Execution Job Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_job_persistence.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


@pytest_asyncio.fixture
async def project(session) -> AsyncIterator[Project]:
    proj = await _make_owner_and_project(session, name="Execution Job Test Project")
    yield proj
    user = await session.get(User, proj.owner_id)
    if user is not None:
        await session.delete(user)
        await session.commit()


def _matmul_create(project: Project, *, input_asset_ids: list[uuid.UUID] | None = None) -> ExecutionJobCreate:
    return ExecutionJobCreate(
        project_id=project.id,
        owner_id=project.owner_id,
        experiment_plan_id=uuid.uuid4(),
        experiment_plan_version=1,
        capability=ExecutionCapability.ARRAY_COMPUTE,
        operation=ExecutionOperation.MATMUL,
        resource_class=ResourceClass.CLASS_ARRAY,
        parameters={"a_asset": "left.csv", "b_asset": "right.csv"},
        input_asset_ids=input_asset_ids or [uuid.uuid4(), uuid.uuid4()],
    )


def _job_from_create(payload: ExecutionJobCreate) -> ExecutionJob:
    data = payload.model_dump()
    data["input_asset_ids"] = [str(asset_id) for asset_id in payload.input_asset_ids]
    return ExecutionJob(**data)


# ---------------------------------------------------------------------------
# Round-trip persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_by_id_round_trips_all_fields(session, project):
    payload = _matmul_create(project)
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    fetched = await ExecutionJobRepository(session).get_by_id(job.id)

    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.project_id == project.id
    assert fetched.owner_id == project.owner_id
    assert fetched.experiment_plan_id == payload.experiment_plan_id
    assert fetched.experiment_plan_version == 1
    assert fetched.capability == ExecutionCapability.ARRAY_COMPUTE
    assert fetched.operation == ExecutionOperation.MATMUL
    assert fetched.resource_class == ResourceClass.CLASS_ARRAY
    assert fetched.parameters == {"a_asset": "left.csv", "b_asset": "right.csv"}
    assert fetched.input_asset_ids == [str(a) for a in payload.input_asset_ids]
    assert fetched.status == ExecutionJobStatus.PENDING
    assert fetched.reason is None
    assert fetched.started_at is None
    assert fetched.completed_at is None


@pytest.mark.asyncio
async def test_status_defaults_to_pending_without_being_set_explicitly(session, project):
    job = await ExecutionJobRepository(session).create(_job_from_create(_matmul_create(project)))
    await session.commit()

    assert job.status == ExecutionJobStatus.PENDING


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_unknown_job(session, project):
    assert await ExecutionJobRepository(session).get_by_id(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_execution_job_read_schema_round_trips_from_orm_row(session, project):
    payload = _matmul_create(project)
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    read = ExecutionJobRead.model_validate(job)

    assert read.id == job.id
    assert read.input_asset_ids == payload.input_asset_ids
    assert all(isinstance(a, uuid.UUID) for a in read.input_asset_ids)
    assert read.status is ExecutionJobStatus.PENDING


@pytest.mark.asyncio
async def test_experiment_plan_id_accepts_a_nonexistent_id(session, project):
    """`experiment_plan_id` is deliberately not a foreign key -- `ExperimentPlan`
    has no backing table yet (verified: no ORM model, no migration references
    it). A row referencing a plan id nobody has created must persist without
    error; this is the documented design choice in `models.py`, not an
    accident."""
    payload = _matmul_create(project)
    job = await ExecutionJobRepository(session).create(_job_from_create(payload))
    await session.commit()

    assert job.experiment_plan_id == payload.experiment_plan_id


@pytest.mark.asyncio
async def test_deleting_project_cascades_to_execution_jobs(session, project):
    job = await ExecutionJobRepository(session).create(_job_from_create(_matmul_create(project)))
    await session.commit()
    job_id = job.id

    user = await session.get(User, project.owner_id)
    await session.delete(user)
    await session.commit()

    # `async_session_factory` is configured with `expire_on_commit=False`
    # (app/database/session.py), so `session`'s own identity map still holds
    # the pre-delete `job` instance after commit -- `session.get()` on it
    # would return that cached object without a query. A second, independent
    # session has no such cache, so it observes the CASCADE delete directly
    # -- the same way a future launcher task, opening its own fresh session,
    # would see it.
    async with async_session_factory() as verify_session:
        assert await ExecutionJobRepository(verify_session).get_by_id(job_id) is None


# ---------------------------------------------------------------------------
# Structural: Rules 1/2/3 compliance
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


@pytest.mark.parametrize(
    "module",
    ["enums", "models", "repository", "schemas"],
)
def test_execution_module_files_never_import_docker_celery_or_subprocess(module):
    import importlib
    import pathlib

    mod = importlib.import_module(f"app.modules.execution.{module}")
    source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    assert not _imports_any_of(source, {"docker", "celery", "subprocess"})


def test_execution_job_repository_has_no_launch_or_dispatch_methods():
    """Structural: this slice is persistence only -- no method resembling
    a launch/dispatch/execute operation exists on the repository.

    Whole-word match on `_`-separated segments, not raw substring: Sprint
    16 Phase 7B.19/7B.21 legitimately added `find_stale_launching_jobs`
    (a pure, read-only detection query naming the `LAUNCHING` *status*,
    not a launch *action*) and `claim_stale_validating_job_for_retry`
    (an atomic status claim, same shape as the already-approved
    `claim_pending_job`, not a launch/dispatch/execute operation
    either) -- a raw substring check flags "launch" inside "launching"
    as a false positive. Word-boundary matching still catches the thing
    this test actually guards against: a method named like
    `launch_container`/`dispatch_job` would split to a segment that
    equals "launch"/"dispatch" outright.
    """
    forbidden_words = {"launch", "dispatch", "execute"}
    forbidden_substrings = ("run_job",)  # multi-word phrase; substring match is fine, no collision risk
    methods = [name for name in dir(ExecutionJobRepository) if not name.startswith("_")]
    for method in methods:
        lowered = method.lower()
        words = set(lowered.split("_"))
        assert not (words & forbidden_words), f"{method} contains a forbidden whole word"
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered


def test_docker_sdk_not_imported_at_runtime_by_execution_module():
    """AST-based (Sprint 16 Phase 7B.25 correction): a `sys.modules`
    check is no longer a valid proxy -- `execution_launcher.launcher`
    now legitimately imports the Docker SDK elsewhere in this codebase,
    and pytest runs the whole suite in one process, so
    `sys.modules["docker"]` can already be populated by an unrelated
    test file by the time this one runs. Checks these three modules'
    own source directly instead."""
    import pathlib

    import app.modules.execution.models as models_module
    import app.modules.execution.repository as repository_module
    import app.modules.execution.schemas as schemas_module

    for module in (models_module, repository_module, schemas_module):
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        assert not _imports_any_of(source, {"docker"}), module.__name__
