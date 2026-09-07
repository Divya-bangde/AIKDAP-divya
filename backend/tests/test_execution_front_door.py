"""Sprint 16 Phase 7B.23 -- the execution front door (plan -> job -> launch).

Twenty-two phases built an execution subsystem nothing could reach. This
file proves the connective tissue: `ExperimentPlanService.request_execution`
(plan -> `ExecutionJob(PENDING)`, committed, launch task enqueued) and the
new `workers.tasks.launch_execution_job` task (the existing, untouched
`prepare_approved_launch` pipeline run to the Docker boundary and no
further).

Follows this codebase's established convention throughout: tests call the
service/router functions directly against a real Postgres session (via the
shared `session`/`project` fixtures from `conftest.py`), never through a
`TestClient` -- there is no existing precedent for HTTP-level testing of
an authenticated business route anywhere in this suite, and router
functions are plain `async def`s that can be awaited directly with the
same objects FastAPI's `Depends()` would have resolved.

`launch_execution_job` is a bound Celery task whose body calls
`asyncio.run()` internally (`_run_task_loop`) -- exactly like
`recover_execution_job_retry` in Sprint 16 Phase 7B.22, any test that
invokes it directly must be a plain `def`, not `async def` (see
`test_celery_task_event_loop.py`), with setup/verify/teardown each
getting their own top-level `asyncio.run()` call instead of the async
fixtures.

Sprint 16 Phase 7B.24 correction: `request_execution`'s original mapping
reused `plan.source_asset_ids` (research/citation context) as
`ExecutionJob.input_asset_ids` (actual execution inputs) -- a semantic
conflation. `ExperimentPlan.execution_input_asset_ids` is now the ONLY
field that ever feeds `input_asset_ids`; `source_asset_ids` never does.
The tests below marked "7B.24" prove that separation directly; the
original V6 test (which deleted a `source_asset_id`-only asset expecting
a guard rejection) tested the WRONG thing under the corrected semantics
and has been replaced by `test_v6a_.../test_v6b_...` below.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.database.session import async_session_factory, engine
from app.modules.assets.enums import AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.auth.models import User
from app.modules.execution.enums import ExecutionJobStatus
from app.modules.execution.models import ExecutionJob
from app.modules.execution.repository import ExecutionAttemptRepository
from app.modules.execution.router import get_execution_job_route, list_execution_jobs_route
from app.modules.execution.service import ExecutionJobNotFoundError, get_owned_job, list_owned_jobs
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.modules.research.experiment_schemas import (
    ExperimentExecuteRequest,
    ExperimentPlanCreateFromEquation,
    ExperimentPlanCreateFromUnderstanding,
)
from app.modules.research.experiment_service import ExperimentPlanNotFoundError, ExperimentPlanService, ExperimentPlanValidationError
from app.modules.research.router import execute_experiment_variant_route
from app.workers.tasks import LAUNCH_GUARD_REJECTED_DIAGNOSTIC, launch_execution_job


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_between_tests():
    await engine.dispose()
    yield


@pytest.fixture
def service(session) -> ExperimentPlanService:
    return ExperimentPlanService(session)


async def _make_owner_and_project(session, *, name: str) -> Project:
    user = User(
        email=f"pytest-frontdoor-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Execution Front Door Test User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    project = Project(
        owner_id=user.id,
        name=name,
        description="Created by test_execution_front_door.py",
        project_type=ProjectType.RESEARCH,
        status=ProjectStatus.ACTIVE,
    )
    session.add(project)
    await session.flush()
    await session.commit()
    return project


async def _teardown_project(project: Project) -> None:
    async with async_session_factory() as session:
        user = await session.get(User, project.owner_id)
        if user is not None:
            await session.delete(user)
            await session.commit()


async def _resolvable_asset(session, project: Project, *, filename: str) -> Asset:
    storage = get_storage_provider()
    storage_path = await storage.save(project_id=project.id, filename=filename, content=b"1,2\n3,4\n")
    asset = Asset(
        project_id=project.id,
        owner_id=project.owner_id,
        title=filename,
        file_name=filename,
        file_extension=filename.rsplit(".", 1)[-1],
        mime_type="text/csv",
        file_size=0,
        storage_path=storage_path,
        checksum="test-checksum",
        asset_type=AssetType.DATASET,
        status=AssetStatus.ACTIVE,
        source=AssetSource.UPLOAD,
        tags=[],
    )
    created = await AssetRepository(session).create(asset)
    await session.commit()
    return created


async def _make_equation_plan(
    service: ExperimentPlanService,
    project: Project,
    *,
    source_asset_id=None,
    execution_input_asset_ids=None,
):
    data = ExperimentPlanCreateFromEquation(
        project_id=project.id,
        title="Front door test plan",
        expression="Y = a*X + b",
        known_inputs=["X"],
        source_asset_id=source_asset_id,
        execution_input_asset_ids=execution_input_asset_ids or [],
    )
    return await service.create_from_equation(project.owner_id, data)


async def _jobs_for_plan(plan_id: uuid.UUID) -> list[ExecutionJob]:
    async with async_session_factory() as verify_session:
        from sqlalchemy import select

        result = await verify_session.execute(
            select(ExecutionJob).where(ExecutionJob.experiment_plan_id == plan_id)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# V1 -- POST /execute on an approved plan creates exactly one PENDING job
# with correct project_id, owner_id, plan id and plan version. 7B.24 test
# item 1: an equation plan with NO declared execution inputs must produce
# input_asset_ids=[] -- never an implicit guess.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_execute_creates_exactly_one_pending_job(service, project, monkeypatch):
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())
    plan = await _make_equation_plan(service, project)

    job = await service.request_execution(project.owner_id, plan.id, "baseline")

    assert job.status == ExecutionJobStatus.PENDING
    assert job.project_id == project.id
    assert job.owner_id == project.owner_id
    assert job.experiment_plan_id == plan.id
    assert job.experiment_plan_version == plan.version
    assert job.input_asset_ids == []  # zero declared execution inputs -> empty, not guessed

    jobs = await _jobs_for_plan(plan.id)
    assert len(jobs) == 1
    assert jobs[0].id == job.id


# ---------------------------------------------------------------------------
# 7B.24 test item 2 -- an equation plan WITH explicit execution inputs maps
# them, and only them, onto ExecutionJob.input_asset_ids.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_7b24_explicit_execution_inputs_are_mapped_onto_the_job(service, project, session, monkeypatch):
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())
    dataset = await _resolvable_asset(session, project, filename="explicit-input.csv")

    plan = await _make_equation_plan(service, project, execution_input_asset_ids=[dataset.id])
    assert plan.execution_input_asset_ids == [dataset.id]

    job = await service.request_execution(project.owner_id, plan.id, "baseline")

    assert job.input_asset_ids == [str(dataset.id)]


# ---------------------------------------------------------------------------
# 7B.24 test items 3 & 7 -- a cited/source paper asset does NOT become an
# execution input, and source_asset_ids retains its original research
# meaning independently of execution_input_asset_ids.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_7b24_cited_source_asset_does_not_become_execution_input(service, project, session, monkeypatch):
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())
    paper = await _resolvable_asset(session, project, filename="cited-paper.csv")

    plan = await _make_equation_plan(service, project, source_asset_id=paper.id)

    # source_asset_ids still means what it always meant...
    assert plan.source_asset_ids == [paper.id]
    # ...and execution_input_asset_ids is NOT implicitly populated from it.
    assert plan.execution_input_asset_ids == []

    job = await service.request_execution(project.owner_id, plan.id, "baseline")

    # The cited paper never reaches the job -- input_asset_ids stays empty.
    assert job.input_asset_ids == []


# ---------------------------------------------------------------------------
# 7B.24 test item 4 -- an execution input asset not owned by the caller (or
# not in the plan's project) is rejected at plan-creation time; no plan and
# no job are created.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_7b24_unauthorized_execution_input_rejected_no_plan_no_job(service, project, session):
    other_project = await _make_owner_and_project(session, name="7B.24 other project")
    foreign_asset = await _resolvable_asset(session, other_project, filename="not-yours.csv")

    with pytest.raises(ExperimentPlanValidationError, match="execution_input_asset_ids"):
        await _make_equation_plan(service, project, execution_input_asset_ids=[foreign_asset.id])

    await _teardown_project(other_project)


# ---------------------------------------------------------------------------
# V2 -- the enqueued launch task actually drives the job forward, with
# attempt #1 created. NOTE: verified against VALIDATING, not LAUNCHING --
# see the module docstring above and the phase report for why.
# ---------------------------------------------------------------------------


def test_v2_launch_task_drives_job_forward_with_attempt_one(monkeypatch):
    """Sprint 16 Phase 7B.25: `launch_execution_job` now calls the REAL
    Docker launcher (`execute_approved_launch`) after guard approval.
    This test's own concern is the FRONT DOOR / pre-Docker state (job
    reaches VALIDATING with exactly one attempt) -- not real Docker
    lifecycle behavior, which `test_execution_real_docker_lifecycle.py`
    covers exhaustively against a real daemon. `execute_approved_launch`
    is stubbed here to keep this test hermetic and to avoid a spurious
    failure caused by the separately-documented missing-real-image gap
    (today's `_APPROVED_IMAGE_DIGESTS` are fake placeholders, so a real
    Docker call here would always 404, regardless of this test's own
    correctness)."""
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())
    from types import SimpleNamespace

    import app.workers.tasks as tasks_module

    async def _fake_execute(*args, **kwargs):
        return SimpleNamespace(succeeded=True, exit_code=0, result_asset_id=None, diagnostic=None)

    monkeypatch.setattr(tasks_module, "execute_approved_launch", _fake_execute)

    async def _setup():
        async with async_session_factory() as session:
            proj = await _make_owner_and_project(session, name="V2 front door project")
            svc = ExperimentPlanService(session)
            plan = await _make_equation_plan(svc, proj)
            job = await svc.request_execution(proj.owner_id, plan.id, "baseline")
            return proj, job

    project, job = asyncio.run(_setup())
    try:
        result = launch_execution_job(str(job.id))  # bound call, not .delay()
        assert result["status"] == "execution_succeeded"

        async def _verify():
            async with async_session_factory() as verify_session:
                reloaded = await verify_session.get(ExecutionJob, job.id)
                attempts = await ExecutionAttemptRepository(verify_session).list_by_job(job.id)
                return reloaded, attempts

        reloaded, attempts = asyncio.run(_verify())
        # ExecutionJobStatus's own docstring: "Only PENDING -> VALIDATING
        # is implemented as of this slice" -- LAUNCHING is reserved
        # (Sprint 16 Phase 7B.19-21, proven under real concurrency) for
        # the retry-recovery claim only. The ORIGINAL launch path this
        # task drives has no code path that ever sets LAUNCHING; adding
        # one would overload a status whose exclusive meaning 7B.21's
        # transaction protocol depends on. Verified against the real,
        # frozen state machine instead of the phase brief's wording.
        assert reloaded.status == ExecutionJobStatus.VALIDATING
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
    finally:
        asyncio.run(_teardown_project(project))


# ---------------------------------------------------------------------------
# V3 -- a plan belonging to another user returns 404 (service raises
# ExperimentPlanNotFoundError; the router maps it to 404), creates no job.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v3_other_users_plan_rejected_creates_no_job(service, project, session, monkeypatch):
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())
    plan = await _make_equation_plan(service, project)

    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Someone Else",
        is_active=True,
    )
    session.add(other)
    await session.flush()

    with pytest.raises(ExperimentPlanNotFoundError):
        await service.request_execution(other.id, plan.id, "baseline")
    assert await _jobs_for_plan(plan.id) == []

    with pytest.raises(HTTPException) as exc_info:
        await execute_experiment_variant_route(
            plan_id=plan.id,
            data=ExperimentExecuteRequest(variant_id="baseline"),
            current_user=SimpleNamespace(id=other.id),
            service=service,
        )
    assert exc_info.value.status_code == 404
    assert await _jobs_for_plan(plan.id) == []

    await session.delete(other)
    await session.commit()


# ---------------------------------------------------------------------------
# V4 -- an unmappable plan (no source_expression) and an unapproved
# variant (status != PLANNED) are both rejected, creating no job.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v4_unmappable_plan_rejected_no_job(service, project, session):
    asset = Asset(
        project_id=project.id,
        owner_id=project.owner_id,
        title="Source paper",
        file_name="paper.txt",
        file_extension="txt",
        mime_type="text/plain",
        file_size=0,
        storage_path="none",
        checksum="none",
        asset_type=AssetType.DOCUMENT,
        status=AssetStatus.ACTIVE,
        source=AssetSource.UPLOAD,
        tags=[],
        description="",
        asset_metadata={
            "research_understanding": {
                "title": "T",
                "problem_statement": "P",
                "variables": [],
                "evaluation_metrics": [],
            }
        },
    )
    await AssetRepository(session).create(asset)
    await session.commit()

    plan = await service.create_from_understanding(
        project.owner_id,
        ExperimentPlanCreateFromUnderstanding(
            project_id=project.id, title="No derivable operation", source_asset_id=asset.id
        ),
    )
    assert plan.source_expression is None

    with pytest.raises(ExperimentPlanValidationError, match="no derivable execution operation"):
        await service.request_execution(project.owner_id, plan.id, "baseline")

    assert await _jobs_for_plan(plan.id) == []


@pytest.mark.asyncio
async def test_v4_unapproved_variant_rejected_no_job(service, project, session):
    plan = await _make_equation_plan(service, project)

    # Nothing in the current codebase ever moves a variant off PLANNED
    # via any API path -- edit the persisted JSON directly to simulate
    # the state a future execution-tracking phase would eventually
    # produce (an already-executed variant), exactly mirroring how
    # `experiment_service._persist_new` stores the plan.
    asset = await AssetRepository(session).get_by_id(plan.id)
    raw = dict(asset.asset_metadata)
    raw_plan = dict(raw["experiment_plan"])
    raw_plan["variants"] = [{**raw_plan["variants"][0], "status": "executed"}]
    asset.asset_metadata = {**raw, "experiment_plan": raw_plan}
    await session.commit()

    with pytest.raises(ExperimentPlanValidationError, match="not eligible for execution"):
        await service.request_execution(project.owner_id, plan.id, "baseline")

    assert await _jobs_for_plan(plan.id) == []


# ---------------------------------------------------------------------------
# V5 -- GET /jobs/{id} returns the job and its attempts for the owner
# only; GET /jobs lists it for the owner only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v5_get_job_and_list_jobs_scoped_to_owner(service, project, session, monkeypatch):
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())
    plan = await _make_equation_plan(service, project)
    job = await service.request_execution(project.owner_id, plan.id, "baseline")

    owned = await get_owned_job(project.owner_id, job.id, session)
    assert owned.id == job.id

    jobs = await list_owned_jobs(project.owner_id, session)
    assert job.id in {j.id for j in jobs}

    detail = await get_execution_job_route(
        job_id=job.id, current_user=SimpleNamespace(id=project.owner_id), session=session
    )
    assert detail.id == job.id
    assert detail.attempts == []  # no launch task has run in this test

    routed_jobs = await list_execution_jobs_route(
        current_user=SimpleNamespace(id=project.owner_id), session=session
    )
    assert job.id in {j.id for j in routed_jobs}

    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Someone Else Too",
        is_active=True,
    )
    session.add(other)
    await session.flush()

    with pytest.raises(ExecutionJobNotFoundError):
        await get_owned_job(other.id, job.id, session)
    assert job.id not in {j.id for j in await list_owned_jobs(other.id, session)}

    with pytest.raises(HTTPException) as exc_info:
        await get_execution_job_route(job_id=job.id, current_user=SimpleNamespace(id=other.id), session=session)
    assert exc_info.value.status_code == 404

    await session.delete(other)
    await session.commit()


# ---------------------------------------------------------------------------
# V6 REINTERPRETED (Sprint 16 Phase 7B.24, test item 5 & 6):
#
# V6-A (Case A) -- a CITED/source paper asset is deleted after plan
# creation. Since source_asset_ids is never mapped onto input_asset_ids,
# this must have NO effect on execution: the guard pipeline never even
# looks at that asset, so it never gets a chance to reject on its absence.
#
# V6-B (Case B) -- an EXPLICITLY DECLARED execution input asset is deleted
# after plan/job creation. This is the scenario the original 7B.23 V6 test
# meant to exercise (it just used the wrong field to do it) -- the guard
# pipeline resolves it, fails, and the launch task diagnoses it on
# job.reason without raising.
# ---------------------------------------------------------------------------


def test_v6a_deleted_cited_source_asset_has_no_effect_on_launch(monkeypatch):
    """Sprint 16 Phase 7B.25: `execute_approved_launch` stubbed for the
    same reason as `test_v2_...` above -- this test's concern is
    source_asset_ids vs execution_input_asset_ids semantics (Phase
    7B.24), not real Docker behavior."""
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())
    from types import SimpleNamespace

    import app.workers.tasks as tasks_module

    async def _fake_execute(*args, **kwargs):
        return SimpleNamespace(succeeded=True, exit_code=0, result_asset_id=None, diagnostic=None)

    monkeypatch.setattr(tasks_module, "execute_approved_launch", _fake_execute)

    async def _setup():
        async with async_session_factory() as session:
            proj = await _make_owner_and_project(session, name="V6a front door project")
            paper = await _resolvable_asset(session, proj, filename="v6a-paper.csv")
            svc = ExperimentPlanService(session)
            plan = await _make_equation_plan(svc, proj, source_asset_id=paper.id)
            job = await svc.request_execution(proj.owner_id, plan.id, "baseline")
            # Deleted AFTER the plan/job reference it as a citation --
            # never as an execution input.
            await AssetRepository(session).delete(paper)
            await session.commit()
            return proj, job

    project, job = asyncio.run(_setup())
    try:
        result = launch_execution_job(str(job.id))  # must not raise
        # The deleted asset was only ever a citation -- launch succeeds
        # exactly as it would have if the asset had never been deleted.
        assert result["status"] == "execution_succeeded"

        async def _verify():
            async with async_session_factory() as verify_session:
                reloaded = await verify_session.get(ExecutionJob, job.id)
                attempts = await ExecutionAttemptRepository(verify_session).list_by_job(job.id)
                return reloaded, attempts

        reloaded, attempts = asyncio.run(_verify())
        assert reloaded.reason is None
        assert len(attempts) == 1
    finally:
        asyncio.run(_teardown_project(project))


def test_v6b_deleted_explicit_execution_input_guard_rejects_no_attempt_no_exception(monkeypatch):
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())

    async def _setup():
        async with async_session_factory() as session:
            proj = await _make_owner_and_project(session, name="V6b front door project")
            dataset = await _resolvable_asset(session, proj, filename="v6b-dataset.csv")
            svc = ExperimentPlanService(session)
            plan = await _make_equation_plan(svc, proj, execution_input_asset_ids=[dataset.id])
            job = await svc.request_execution(proj.owner_id, plan.id, "baseline")
            assert job.input_asset_ids == [str(dataset.id)]
            # Deleted AFTER the plan/job already declare it as an
            # execution input -- a real, later event, not a fabricated
            # precondition.
            await AssetRepository(session).delete(dataset)
            await session.commit()
            return proj, job

    project, job = asyncio.run(_setup())
    try:
        result = launch_execution_job(str(job.id))  # must not raise
        assert result["status"] == "guard_rejected"

        async def _verify():
            async with async_session_factory() as verify_session:
                reloaded = await verify_session.get(ExecutionJob, job.id)
                attempts = await ExecutionAttemptRepository(verify_session).list_by_job(job.id)
                return reloaded, attempts

        reloaded, attempts = asyncio.run(_verify())
        assert reloaded.reason == LAUNCH_GUARD_REJECTED_DIAGNOSTIC
        assert attempts == []
    finally:
        asyncio.run(_teardown_project(project))


# ---------------------------------------------------------------------------
# 7B.24 test item 9 -- repeated execution of the same PLANNED variant is
# characterized, not fixed. Nothing currently writes RunPlanStatus.EXECUTED
# or otherwise consumes a variant, so calling request_execution twice for
# the same plan+variant is CURRENTLY ALLOWED: it produces two independent
# ExecutionJob rows, each safe on its own (the already-proven Phase 7B.11/
# 7B.14/7B.21 per-job concurrency protocol governs each independently).
# This is a product-level idempotency gap, not a data-corruption risk --
# documented here as the smallest correct characterization, not fixed
# (explicitly out of scope for this phase; see the phase report for the
# identified smallest future slice).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_7b24_repeated_variant_execution_is_currently_allowed_two_jobs(service, project, monkeypatch):
    monkeypatch.setattr(launch_execution_job, "delay", MagicMock())
    plan = await _make_equation_plan(service, project)

    first_job = await service.request_execution(project.owner_id, plan.id, "baseline")
    second_job = await service.request_execution(project.owner_id, plan.id, "baseline")

    assert first_job.id != second_job.id
    jobs = await _jobs_for_plan(plan.id)
    assert len(jobs) == 2
    assert {j.id for j in jobs} == {first_job.id, second_job.id}
