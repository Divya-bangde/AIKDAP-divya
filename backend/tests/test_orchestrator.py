"""Sprint 8: orchestrator hardening — state, registry, routing, failures.

Complements `test_research_citations.py`, which covers evidence and
citation propagation. These tests cover the orchestration layer around
it: the shared state contract, the agent registry, conditional routing,
per-node execution tracking, and the critical/non-critical failure
policy.

Every test is deterministic and offline. External providers are
replaced with fakes through `GraphDependencies`, which the graph
already injects per run, so no test reaches a network or a paid API.
"""

import uuid
from typing import Any

import pytest

from app.agents.planner.graph import (
    build_research_graph,
    get_research_graph,
    workflow_node_order,
)
from app.agents.planner.nodes import (
    ExtractiveSynthesizer,
    GraphDependencies,
    MockWebResearchProvider,
    build_dependencies,
)
from app.agents.planner.planner import get_planner
from app.agents.planner.registry import (
    AGENT_REGISTRY,
    NodeSpec,
    get_node_spec,
    registered_agents,
    retrieval_agents,
)
from app.agents.planner.state import (
    ResearchNode,
    ResearchState,
    degraded_warnings,
)
from app.agents.planner.tracking import (
    TRACKER_CONFIG_KEY,
    NodeExecutionTracker,
    NullTracker,
    instrument,
)
from app.modules.research.enums import (
    ResearchRunStatus,
    ResearchStepStatus,
)
from app.modules.research.models import ResearchRun
from app.modules.research.repository import ResearchStepRepository
from app.modules.research.service import ResearchExecutionService, ResearchStepTracker

QUERY = "Analyze the Indian poultry industry: trends, challenges, opportunities."

EXPECTED_AGENTS = {
    "planner",
    "router",
    "web_research",
    "asset_retrieval",
    "context_builder",
    "synthesis",
}


# ---------------------------------------------------------------------------
# Fakes — deterministic, offline
# ---------------------------------------------------------------------------


class FakeAssetRetriever:
    """Returns a fixed knowledge-base document without touching the DB."""

    name = "fake_asset_retriever"

    def __init__(self, count: int = 2) -> None:
        self._count = count

    async def retrieve(self, *, owner_id, project_id, query, limit):
        return [
            {
                "source": "asset",
                "provider": self.name,
                "reference": f"asset:{project_id}#chunk-{index}",
                "title": f"Fake asset chunk {index}",
                "snippet": "Poultry production grew steadily over the period.",
                "score": 0.9 - index * 0.1,
                "simulated": False,
            }
            for index in range(min(self._count, limit))
        ]


class BrokenAssetRetriever:
    """Raises, to exercise the non-critical failure path."""

    name = "broken_asset_retriever"

    async def retrieve(self, *, owner_id, project_id, query, limit):
        raise RuntimeError("knowledge base unavailable")


class BrokenPlanner:
    """Raises, to exercise the critical failure path."""

    name = "broken_planner"

    async def plan(self, request):
        raise RuntimeError("planner backend unavailable")


def make_dependencies(**overrides: Any) -> GraphDependencies:
    """Default offline dependency set, with per-test overrides."""
    defaults: dict[str, Any] = {
        "planner": get_planner(),
        "asset_retriever": FakeAssetRetriever(),
        "web_provider": MockWebResearchProvider(),
        "synthesizer": ExtractiveSynthesizer(),
    }
    defaults.update(overrides)
    return GraphDependencies(**defaults)


def make_config(dependencies: GraphDependencies, tracker=None) -> dict[str, Any]:
    """Graph config carrying the injected dependencies and tracker."""
    return {
        "configurable": {
            "dependencies": dependencies,
            TRACKER_CONFIG_KEY: tracker or NullTracker(),
        }
    }


def initial_state(**overrides: Any) -> dict[str, Any]:
    """A complete graph input state."""
    state: dict[str, Any] = {
        "run_id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
        "owner_id": str(uuid.uuid4()),
        "task_id": None,
        "query": QUERY,
        "include_assets": True,
        "include_web": True,
        "max_results": 3,
        "status": ResearchRunStatus.RUNNING.value,
    }
    state.update(overrides)
    return state


class RecordingTracker(NodeExecutionTracker):
    """In-memory tracker, so tracking can be asserted without a database."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.succeeded: list[tuple[str, int]] = []
        self.failed: list[tuple[str, str, bool]] = []

    async def on_node_start(self, node: str) -> None:
        self.started.append(node)

    async def on_node_success(self, node, update, duration_ms) -> None:
        self.succeeded.append((node, duration_ms))

    async def on_node_failure(self, node, error, duration_ms, critical) -> None:
        self.failed.append((node, type(error).__name__, critical))


# ---------------------------------------------------------------------------
# TEST 1 — shared state carries every required workflow field
# ---------------------------------------------------------------------------


def test_shared_state_declares_all_workflow_fields():
    """One canonical state must declare every Sprint 8 field."""
    required = {
        "run_id",
        "project_id",
        "task_id",
        "query",
        "objective",
        "plan",
        "selected_agents",
        "retrieved_documents",
        "context",
        "citations",
        "intermediate_results",
        "final_answer",
        "status",
        "error",
    }
    declared = set(ResearchState.__annotations__)
    assert required <= declared, f"missing from state: {sorted(required - declared)}"


@pytest.mark.asyncio
async def test_shared_state_round_trips_every_field_through_the_graph():
    """A full state must survive a real graph execution."""
    state = initial_state(task_id=str(uuid.uuid4()))
    final = await get_research_graph().ainvoke(state, config=make_config(make_dependencies()))

    # Inputs preserved.
    assert final["run_id"] == state["run_id"]
    assert final["task_id"] == state["task_id"]
    assert final["query"] == QUERY
    # Outputs produced.
    assert final["objective"]
    assert final["plan"]
    assert final["selected_agents"]
    assert final["retrieved_documents"]
    assert final["context"]
    assert final["citations"]
    assert final["final_answer"]
    assert final["status"] == ResearchRunStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# TEST 2 — the registry contains every current agent
# ---------------------------------------------------------------------------


def test_registry_contains_all_current_agents():
    """All six Sprint 7 capabilities must be registered."""
    assert set(registered_agents()) == EXPECTED_AGENTS
    assert set(AGENT_REGISTRY) == EXPECTED_AGENTS

    for name in EXPECTED_AGENTS:
        spec = get_node_spec(name)
        assert isinstance(spec, NodeSpec)
        assert spec.name == name
        assert spec.title and spec.description
        assert callable(spec.handler)


def test_registry_marks_retrieval_agents_non_critical():
    """Only the routable retrieval agents may be non-critical."""
    assert set(retrieval_agents()) == {"web_research", "asset_retrieval"}
    for name in retrieval_agents():
        assert get_node_spec(name).critical is False
    for name in EXPECTED_AGENTS - set(retrieval_agents()):
        assert get_node_spec(name).critical is True


def test_registry_rejects_unknown_agent():
    """An unknown agent name must fail loudly, not silently."""
    with pytest.raises(KeyError):
        get_node_spec("no_such_agent")


def test_graph_nodes_come_from_the_registry():
    """Every registered agent must appear as a node in the compiled graph."""
    nodes = set(build_research_graph().compile().get_graph().nodes)
    assert EXPECTED_AGENTS <= nodes
    assert set(workflow_node_order()) == EXPECTED_AGENTS


# ---------------------------------------------------------------------------
# TEST 3 — the graph executes the basic research workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_executes_basic_workflow_in_order():
    """A both-sources run must execute all six agents, spine last."""
    tracker = RecordingTracker()
    await get_research_graph().ainvoke(
        initial_state(), config=make_config(make_dependencies(), tracker)
    )

    assert tracker.started == [
        ResearchNode.PLANNER.value,
        ResearchNode.ROUTER.value,
        ResearchNode.ASSET_RETRIEVAL.value,
        ResearchNode.WEB_RESEARCH.value,
        ResearchNode.CONTEXT_BUILDER.value,
        ResearchNode.SYNTHESIS.value,
    ]
    assert [node for node, _ in tracker.succeeded] == tracker.started
    assert tracker.failed == []


# ---------------------------------------------------------------------------
# TEST 4 & 5 — conditional routing skips and executes the right agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("include_assets", "include_web", "expected_retrieval"),
    [
        (True, False, ["asset_retrieval"]),
        (False, True, ["web_research"]),
        (True, True, ["asset_retrieval", "web_research"]),
        (False, False, []),
    ],
)
async def test_routing_executes_only_selected_agents(
    include_assets, include_web, expected_retrieval
):
    """Unselected retrieval agents must never be entered."""
    tracker = RecordingTracker()
    final = await get_research_graph().ainvoke(
        initial_state(include_assets=include_assets, include_web=include_web),
        config=make_config(make_dependencies(), tracker),
    )

    executed_retrieval = [n for n in tracker.started if n in set(retrieval_agents())]
    assert executed_retrieval == expected_retrieval
    assert final["selected_agents"] == expected_retrieval

    # The spine always runs, whatever the routing decision.
    for spine in ("planner", "router", "context_builder", "synthesis"):
        assert spine in tracker.started


@pytest.mark.asyncio
async def test_skipped_agent_never_executes_its_handler():
    """A skipped agent's business logic must not run at all.

    `_UnusedAssetRetriever`-style guard: the retriever raises if
    touched, so reaching completion proves it was routed around rather
    than executed and ignored.
    """
    final = await get_research_graph().ainvoke(
        initial_state(include_assets=False),
        config=make_config(make_dependencies(asset_retriever=BrokenAssetRetriever())),
    )
    assert final["status"] == ResearchRunStatus.COMPLETED.value
    assert "asset_retrieval" not in final["selected_agents"]


# ---------------------------------------------------------------------------
# TEST 6 — failure handling, critical and non-critical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_critical_failure_continues_and_warns_synthesis():
    """A failed retrieval agent must degrade the run, not abort it."""
    tracker = RecordingTracker()
    final = await get_research_graph().ainvoke(
        initial_state(),
        config=make_config(
            make_dependencies(asset_retriever=BrokenAssetRetriever()), tracker
        ),
    )

    assert ("asset_retrieval", "RuntimeError", False) in tracker.failed
    # The run still completes, using the evidence that was available.
    assert final["status"] == ResearchRunStatus.COMPLETED.value
    assert final["citations"], "web evidence should still have been used"

    # The failure is visible in state and disclosed in the answer.
    assert "asset_retrieval_failure" in final["intermediate_results"]
    warnings = degraded_warnings(final)
    assert warnings and "asset_retrieval" in warnings[0]
    assert "Incomplete evidence" in final["final_answer"]


@pytest.mark.asyncio
async def test_critical_failure_aborts_the_graph():
    """A failed planner must propagate, not produce a fake answer."""
    tracker = RecordingTracker()
    with pytest.raises(RuntimeError, match="planner backend unavailable"):
        await get_research_graph().ainvoke(
            initial_state(),
            config=make_config(make_dependencies(planner=BrokenPlanner()), tracker),
        )

    assert ("planner", "RuntimeError", True) in tracker.failed
    # Nothing downstream ran.
    assert tracker.started == ["planner"]
    assert tracker.succeeded == []


@pytest.mark.asyncio
async def test_instrument_preserves_handler_output():
    """Instrumentation must never rewrite a successful node's update."""

    async def handler(state, config):
        return {"context": "untouched", "step": {"summary": "ok"}}

    spec = NodeSpec(
        name="probe", title="Probe", handler=handler, critical=True, description="test"
    )
    result = await instrument(spec)({}, make_config(make_dependencies()))
    assert result == {"context": "untouched", "step": {"summary": "ok"}}


# ---------------------------------------------------------------------------
# TEST 6b, 7, 8, 9 — persistence through the real execution service
# ---------------------------------------------------------------------------


async def _run_to_completion(
    session, project, *, dependencies: GraphDependencies, **run_kwargs
) -> ResearchRun:
    """Create and execute a research run against the real database."""
    run = ResearchRun(
        project_id=project.id,
        owner_id=project.owner_id,
        query=QUERY,
        status=ResearchRunStatus.PENDING,
        include_assets=run_kwargs.pop("include_assets", True),
        include_web=run_kwargs.pop("include_web", True),
        max_results=3,
        **run_kwargs,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    from app.modules.research import service as service_module

    original = service_module.build_dependencies
    service_module.build_dependencies = lambda _session: dependencies
    try:
        await ResearchExecutionService(session).execute(run.id)
    finally:
        service_module.build_dependencies = original

    await session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_successful_run_persists_answer_citations_and_steps(session, project):
    """TEST 7, 8, 9 — a completed run persists its full trace."""
    run = await _run_to_completion(session, project, dependencies=make_dependencies())

    # TEST 7 — final answer persisted.
    assert run.status is ResearchRunStatus.COMPLETED
    assert run.final_answer
    assert run.objective and run.plan
    assert run.started_at and run.completed_at and run.duration_ms is not None

    # TEST 8 — citations survive the complete graph, still structured.
    assert run.citations
    assert all(isinstance(c, dict) and "reference" in c for c in run.citations)
    assert any(c["simulated"] is False for c in run.citations), "asset evidence grounded"
    assert any(c["simulated"] is True for c in run.citations), "web evidence simulated"

    # TEST 9 — research_steps hold the correct node sequence.
    steps = await ResearchStepRepository(session).list_by_run(run.id)
    assert [s.step_index for s in steps] == list(range(len(steps)))
    assert [s.node_name for s in steps] == [
        "planner",
        "router",
        "asset_retrieval",
        "web_research",
        "context_builder",
        "synthesis",
    ]
    for step in steps:
        assert step.status is ResearchStepStatus.COMPLETED
        assert step.duration_ms is not None
        assert step.started_at and step.completed_at
        assert step.title and step.summary

    # No registered node silently disappears from the trace.
    assert {s.node_name for s in steps} == EXPECTED_AGENTS


@pytest.mark.asyncio
async def test_skipped_agent_is_recorded_as_a_step(session, project):
    """A routed-around agent must appear as `skipped`, not vanish."""
    run = await _run_to_completion(
        session, project, dependencies=make_dependencies(), include_assets=False
    )

    steps = {s.node_name: s for s in await ResearchStepRepository(session).list_by_run(run.id)}
    assert set(steps) == EXPECTED_AGENTS
    assert steps["asset_retrieval"].status is ResearchStepStatus.SKIPPED
    assert steps["asset_retrieval"].summary
    assert steps["web_research"].status is ResearchStepStatus.COMPLETED
    assert run.status is ResearchRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_non_critical_node_failure_is_persisted(session, project):
    """TEST 6 — a non-critical failure is recorded and the run completes."""
    run = await _run_to_completion(
        session,
        project,
        dependencies=make_dependencies(asset_retriever=BrokenAssetRetriever()),
    )

    steps = {s.node_name: s for s in await ResearchStepRepository(session).list_by_run(run.id)}
    failed = steps["asset_retrieval"]
    assert failed.status is ResearchStepStatus.FAILED
    assert "knowledge base unavailable" in failed.error_message
    assert failed.duration_ms is not None

    # Degraded, not aborted: the run still delivers what it could.
    assert run.status is ResearchRunStatus.COMPLETED
    assert run.final_answer
    assert "Incomplete evidence" in run.final_answer


@pytest.mark.asyncio
async def test_critical_node_failure_fails_the_run(session, project):
    """A critical failure fails the run and persists the error."""
    run = await _run_to_completion(
        session, project, dependencies=make_dependencies(planner=BrokenPlanner())
    )

    assert run.status is ResearchRunStatus.FAILED
    assert "planner backend unavailable" in run.error_message
    assert run.final_answer is None, "a failed run must not fabricate an answer"
    assert run.completed_at and run.duration_ms is not None

    steps = {s.node_name: s for s in await ResearchStepRepository(session).list_by_run(run.id)}
    assert steps["planner"].status is ResearchStepStatus.FAILED
    assert "planner backend unavailable" in steps["planner"].error_message


@pytest.mark.asyncio
async def test_tracker_records_running_before_completion(session, project):
    """A step must be observable as `running` while its node executes."""
    run = ResearchRun(
        project_id=project.id,
        owner_id=project.owner_id,
        query=QUERY,
        status=ResearchRunStatus.PENDING,
        include_assets=False,
        include_web=True,
        max_results=3,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    tracker = ResearchStepTracker(session, run.id)
    await tracker.on_node_start("planner")

    steps = await ResearchStepRepository(session).list_by_run(run.id)
    assert len(steps) == 1
    assert steps[0].status is ResearchStepStatus.RUNNING
    assert steps[0].started_at is not None
    assert steps[0].completed_at is None

    await tracker.on_node_success("planner", {"step": {"summary": "done"}}, 12)
    steps = await ResearchStepRepository(session).list_by_run(run.id)
    assert steps[0].status is ResearchStepStatus.COMPLETED
    assert steps[0].duration_ms == 12
    assert steps[0].summary == "done"


# ---------------------------------------------------------------------------
# TEST 10 — the Celery task invokes the orchestrator
# ---------------------------------------------------------------------------


def test_celery_task_is_registered_and_calls_the_orchestrator(monkeypatch):
    """The worker task must drive `ResearchExecutionService.execute`."""
    from app.workers import tasks as worker_tasks
    from app.workers.celery_app import celery_app

    assert "workers.execute_research_run" in celery_app.tasks

    run_id = uuid.uuid4()
    called: dict[str, Any] = {}

    class FakeExecutionService:
        def __init__(self, session):
            called["session"] = session

        async def execute(self, incoming_run_id):
            called["run_id"] = incoming_run_id

    monkeypatch.setattr(worker_tasks, "ResearchExecutionService", FakeExecutionService)

    result = worker_tasks.execute_research_run.run(str(run_id))

    assert called["run_id"] == run_id
    assert called["session"] is not None
    assert result == {"status": "ok", "run_id": str(run_id)}


def test_build_dependencies_supplies_every_strategy():
    """The default dependency set must populate all four strategies."""
    dependencies = build_dependencies(session=None)
    assert dependencies.planner is not None
    assert dependencies.asset_retriever is not None
    assert dependencies.web_provider is not None
    assert dependencies.synthesizer is not None


class QueryingBrokenAssetRetriever:
    """Reads from the database, then fails — like the real retriever.

    `BrokenAssetRetriever` raises before touching the session, which
    leaves no transaction for the tracker's rollback to discard. The
    real `SemanticAssetRetriever` validates ownership against the
    database *first* and can then fail on the embedding call, so the
    rollback has live state to expire. Only that ordering reproduces
    the defect below.
    """

    name = "querying_broken_asset_retriever"

    def __init__(self, session) -> None:
        self._session = session

    async def retrieve(self, *, owner_id, project_id, query, limit):
        from sqlalchemy import select

        from app.modules.projects.models import Project

        await self._session.execute(select(Project).where(Project.id == project_id))
        raise RuntimeError("embedding provider unreachable")


@pytest.mark.asyncio
async def test_non_critical_failure_with_a_skipped_node_still_completes(
    session, project
):
    """A degraded run that also skips a node must still record itself.

    Regression test for a latent defect found in Sprint 9E. The two
    halves were each covered already — a non-critical failure (TEST 6)
    and a skipped node (TEST 5) — but never together, and only the
    combination breaks: the failure rolls the session back, which
    expires the `ResearchRun` instance, and the skipped-node bookkeeping
    is the first thing afterwards to read an attribute off it. That
    lazy load cannot be serviced by async SQLAlchemy, so a run that had
    successfully degraded died while writing its own record.
    """
    run = await _run_to_completion(
        session,
        project,
        dependencies=make_dependencies(
            asset_retriever=QueryingBrokenAssetRetriever(session)
        ),
        # Forces `web_research` to be skipped, so the skipped-node loop
        # actually executes after the rollback.
        include_web=False,
    )

    steps = {s.node_name: s for s in await ResearchStepRepository(session).list_by_run(run.id)}
    assert steps["asset_retrieval"].status is ResearchStepStatus.FAILED
    assert steps["web_research"].status is ResearchStepStatus.SKIPPED
    assert run.status is ResearchRunStatus.COMPLETED
    assert run.final_answer
