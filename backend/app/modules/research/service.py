"""Business logic for the research workspace.

Two services, split by who calls them:

- `ResearchService` — request-scoped, used by the router. Validates
  ownership, creates the run, dispatches it, and reads runs back. It
  never executes the workflow.
- `ResearchExecutionService` — worker-scoped, used by the Celery task.
  Drives the LangGraph workflow and writes the Explainable-AI trace.

Ownership is enforced transitively through the project, exactly as in
the projects/assets/tasks modules: "exists but not yours" and "doesn't
exist" both surface as `ResearchRunNotFoundError`, so ownership is
never leaked to the caller.
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planner.graph import get_research_graph, workflow_node_order
from app.agents.planner.nodes import build_dependencies
from app.agents.planner.registry import get_node_spec
from app.agents.planner.state import ResearchNode
from app.agents.planner.tracking import TRACKER_CONFIG_KEY, NodeExecutionTracker
from app.core.logging.logger import get_logger
from app.modules.projects.repository import ProjectRepository
from app.modules.research.enums import (
    AgentMessageRole,
    ResearchGroundingStatus,
    ResearchRunStatus,
    ResearchStepStatus,
)
from app.modules.research.models import AgentMessage, ResearchRun, ResearchStep
from app.modules.research.repository import (
    AgentMessageRepository,
    ResearchRunRepository,
    ResearchStepRepository,
)
from app.modules.research.schemas import ResearchRunCreate
from app.modules.tasks.repository import TaskRepository

logger = get_logger(__name__)


class ResearchRunNotFoundError(Exception):
    """Raised when a run does not exist or is not owned by the caller."""


class ProjectAccessDeniedError(Exception):
    """Raised when the caller does not own the project a run belongs to."""


class TaskAccessDeniedError(Exception):
    """Raised when the caller does not own the task a run is linked to."""


class ResearchService:
    """Request-scoped coordination of research run creation and retrieval."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._runs = ResearchRunRepository(session)
        self._steps = ResearchStepRepository(session)
        self._messages = AgentMessageRepository(session)
        self._projects = ProjectRepository(session)
        self._tasks = TaskRepository(session)

    async def _ensure_project_owned(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> None:
        project = await self._projects.get_by_id(project_id)
        if project is None or project.owner_id != owner_id:
            raise ProjectAccessDeniedError(project_id)

    async def _ensure_task_owned(self, owner_id: uuid.UUID, task_id: uuid.UUID) -> None:
        task = await self._tasks.get_by_id(task_id)
        if task is None or task.owner_id != owner_id:
            raise TaskAccessDeniedError(task_id)

    async def start_run(self, owner_id: uuid.UUID, data: ResearchRunCreate) -> ResearchRun:
        """Create a research run and hand it to the worker.

        The workflow is never executed here. The row is committed first
        so the worker can always find what it is asked to process, then
        the Celery task is published; `.delay()` only puts a message on
        the broker and returns, so the caller's request is not blocked
        by any part of the research itself.
        """
        await self._ensure_project_owned(owner_id, data.project_id)
        if data.task_id is not None:
            await self._ensure_task_owned(owner_id, data.task_id)

        run = ResearchRun(
            project_id=data.project_id,
            owner_id=owner_id,
            task_id=data.task_id,
            query=data.query,
            status=ResearchRunStatus.PENDING,
            include_assets=data.include_assets,
            include_web=data.include_web,
            max_results=data.max_results,
        )
        created = await self._runs.create(run)
        await self._session.commit()

        logger.info(
            "research_run_created",
            run_id=str(created.id),
            project_id=str(created.project_id),
            owner_id=str(owner_id),
            include_assets=created.include_assets,
            include_web=created.include_web,
            max_results=created.max_results,
        )

        # Imported here, not at module scope: `app.workers.tasks`
        # imports this module to reach `ResearchExecutionService`, so a
        # top-level import would be circular. A function-scoped import
        # breaks the cycle while keeping the strong, checkable
        # reference to the task (rather than dispatching by name).
        from app.workers.tasks import execute_research_run

        async_result = execute_research_run.delay(str(created.id))
        logger.info(
            "celery_task_dispatched",
            task_name=execute_research_run.name,
            run_id=str(created.id),
        )
        logger.info(
            "celery_task_id_returned", task_id=async_result.id, run_id=str(created.id)
        )

        created.celery_task_id = async_result.id
        await self._session.commit()
        await self._session.refresh(created)
        return created

    async def get_owned_run(self, owner_id: uuid.UUID, run_id: uuid.UUID) -> ResearchRun:
        """Fetch a run, ensuring it belongs to the given user."""
        run = await self._runs.get_by_id(run_id)
        if run is None or run.owner_id != owner_id:
            raise ResearchRunNotFoundError(run_id)
        return run

    async def list_runs(
        self,
        owner_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        status: ResearchRunStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ResearchRun]:
        """List the current user's runs, optionally filtered."""
        if project_id is not None:
            await self._ensure_project_owned(owner_id, project_id)
        return await self._runs.list_by_owner(
            owner_id, project_id=project_id, status=status, skip=skip, limit=limit
        )

    async def get_trace(
        self, run: ResearchRun
    ) -> tuple[list[ResearchStep], list[AgentMessage]]:
        """Load the Explainable-AI trace for an already-authorized run."""
        steps = await self._steps.list_by_run(run.id)
        messages = await self._messages.list_by_run(run.id)
        return steps, messages


class ResearchExecutionService:
    """Worker-scoped execution of the LangGraph research workflow.

    Owns the run lifecycle (`pending -> running -> completed|failed`)
    and delegates per-node tracking to `ResearchStepTracker`, which the
    orchestrator calls as each agent starts and finishes. Steps are
    therefore written *while* the graph runs, not reconstructed after
    it: a run in progress is observable through the API, and a run that
    fails halfway keeps a complete record of everything before it.

    Never raises for workflow failures: like the asset processing
    pipeline, the row is the source of truth for "did this succeed",
    queryable via `GET /research/runs/{id}` rather than buried in
    Celery's result backend. Infrastructure failures (an unreachable
    database) still propagate, so the task's retry policy applies.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._runs = ResearchRunRepository(session)
        self._steps = ResearchStepRepository(session)
        self._messages = AgentMessageRepository(session)

    async def execute(self, run_id: uuid.UUID) -> None:
        """Run the workflow for one research run, recording every step."""
        run = await self._runs.get_by_id(run_id)
        if run is None:
            logger.warning("research_run_missing", run_id=str(run_id))
            return

        run.status = ResearchRunStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        run.error_message = None
        await self._session.commit()

        logger.info(
            "research_run_started",
            run_id=str(run.id),
            status=run.status.value,
            query=run.query,
        )

        monotonic_start = time.monotonic()
        tracker = ResearchStepTracker(self._session, run.id)

        try:
            final_state = await self._invoke_graph(run, tracker)
        except Exception as exc:  # noqa: BLE001 - recorded on the run, not swallowed
            # A critical node aborted the graph. It may have failed
            # mid-statement, so roll back before writing the failure or
            # that commit fails too.
            await self._session.rollback()
            await self._fail(run_id, monotonic_start, exc)
            return

        # Re-fetch rather than reuse the instance the graph ran against,
        # for the same reason `_fail` does: a *non-critical* node
        # failure also rolls the session back mid-run, and a rollback
        # expires every object in it. Reading an expired attribute
        # afterwards triggers a lazy load that async SQLAlchemy cannot
        # service, which surfaces as `MissingGreenlet` — a run that
        # degraded successfully would then die while writing its own
        # record.
        run = await self._runs.get_by_id(run_id)
        if run is None:
            logger.error("research_run_vanished_mid_execution", run_id=str(run_id))
            return

        await self._record_skipped(run, tracker)
        await self._complete(run, monotonic_start, final_state)

    async def _invoke_graph(
        self, run: ResearchRun, tracker: "ResearchStepTracker"
    ) -> dict[str, Any]:
        """Execute the compiled graph and return its final state.

        The strategies, the database session, and the tracker are all
        injected per run through the graph config — the compiled graph
        itself holds no run-specific state.
        """
        initial_state = {
            "run_id": str(run.id),
            "project_id": str(run.project_id),
            "owner_id": str(run.owner_id),
            "task_id": str(run.task_id) if run.task_id else None,
            "query": run.query,
            "include_assets": run.include_assets,
            "include_web": run.include_web,
            "max_results": run.max_results,
            "status": ResearchRunStatus.RUNNING.value,
        }
        config = {
            "configurable": {
                "dependencies": build_dependencies(self._session),
                TRACKER_CONFIG_KEY: tracker,
            }
        }
        return await get_research_graph().ainvoke(initial_state, config=config)

    async def _record_skipped(
        self, run: ResearchRun, tracker: "ResearchStepTracker"
    ) -> None:
        """Record the agents that never ran, and why.

        A trace that only shows what executed hides the decision that
        mattered; the constitution requires routing itself to be
        explainable, and no registered node may silently disappear from
        a run's trace.
        """
        skipped = [
            name for name in workflow_node_order() if name not in tracker.executed_nodes
        ]
        for name in skipped:
            await self._steps.create(
                ResearchStep(
                    run_id=run.id,
                    step_index=tracker.next_step_index(),
                    node_name=name,
                    title=f"Skipped: {name}",
                    status=ResearchStepStatus.SKIPPED,
                    summary=_skip_reason(ResearchNode(name), run),
                    started_at=None,
                    completed_at=None,
                    duration_ms=None,
                )
            )
            logger.info(
                "research_step_skipped", run_id=str(run.id), node=name, status="skipped"
            )
        if skipped:
            await self._session.commit()

    async def _complete(
        self, run: ResearchRun, monotonic_start: float, final_state: dict[str, Any]
    ) -> None:
        """Close out a successful run with its deliverable."""
        run.status = ResearchRunStatus.COMPLETED
        run.objective = final_state.get("objective")
        run.plan = final_state.get("plan")
        run.final_answer = final_state.get("final_answer")
        run.citations = final_state.get("citations") or []
        # Read back as an enum so an unexpected value fails here rather
        # than being written to the column verbatim.
        grounding = final_state.get("grounding_status")
        run.grounding_status = (
            ResearchGroundingStatus(grounding) if grounding else None
        )
        run.completed_at = datetime.now(timezone.utc)
        run.duration_ms = _elapsed_ms(monotonic_start)
        await self._session.commit()

        logger.info(
            "research_run_completed",
            run_id=str(run.id),
            status=run.status.value,
            duration_ms=run.duration_ms,
            citation_count=len(run.citations or []),
            grounding_status=run.grounding_status.value if run.grounding_status else None,
        )

    async def _fail(
        self, run_id: uuid.UUID, monotonic_start: float, exc: Exception
    ) -> None:
        """Close out a failed run, preserving the steps already recorded.

        Re-fetches the run rather than reusing the caller's instance:
        the rollback that precedes this call expires every object in
        the session, and touching an expired attribute would trigger a
        lazy load that async SQLAlchemy cannot service.
        """
        run = await self._runs.get_by_id(run_id)
        if run is None:
            logger.error(
                "research_run_failed_and_missing",
                run_id=str(run_id),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return

        run.status = ResearchRunStatus.FAILED
        run.error_message = f"{type(exc).__name__}: {exc}"
        run.completed_at = datetime.now(timezone.utc)
        run.duration_ms = _elapsed_ms(monotonic_start)
        await self._session.commit()

        logger.error(
            "research_run_failed",
            run_id=str(run.id),
            error_type=type(exc).__name__,
            error_message=str(exc),
            duration_ms=run.duration_ms,
        )


class ResearchStepTracker(NodeExecutionTracker):
    """Writes the `research_steps` trace as the graph executes.

    The database-backed implementation of the orchestrator's tracking
    contract. It is the only writer of step rows, so step ordering,
    timing, and the transcript all follow one rule rather than being
    reconstructed by whoever happens to observe the graph.

    Each node produces exactly one row, moving `running -> completed`
    or `running -> failed`. The `running` row is committed before the
    node executes, which is what makes an in-flight run observable
    through `GET /research/runs/{id}`.

    No second execution-tracking table is introduced: this uses the
    existing `research_steps` and `agent_messages` models and the
    existing `ResearchStepStatus` enum values.
    """

    def __init__(self, session: AsyncSession, run_id: uuid.UUID) -> None:
        self._session = session
        self._run_id = run_id
        self._steps = ResearchStepRepository(session)
        self._messages = AgentMessageRepository(session)
        self._step_index = 0
        self._message_sequence = 0
        # Stored as a plain UUID, not an ORM instance: a rollback in
        # the failure path expires every object in the session, and
        # touching an expired attribute would trigger a lazy load that
        # async SQLAlchemy cannot service.
        self._current_step_id: uuid.UUID | None = None
        self.executed_nodes: list[str] = []

    def next_step_index(self) -> int:
        """Return the next step position and advance the counter."""
        index = self._step_index
        self._step_index += 1
        return index

    async def on_node_start(self, node: str) -> None:
        """Open a `running` step row before the agent executes."""
        spec = get_node_spec(node)
        step = await self._steps.create(
            ResearchStep(
                run_id=self._run_id,
                step_index=self.next_step_index(),
                node_name=node,
                title=spec.title,
                status=ResearchStepStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
        )
        self._current_step_id = step.id
        self.executed_nodes.append(node)
        await self._session.commit()

    async def on_node_success(
        self, node: str, update: dict[str, Any], duration_ms: int
    ) -> None:
        """Close the step as completed and persist the agent transcript."""
        step = await self._current_step()
        if step is None:
            return

        report = update.get("step") or {}
        step.status = ResearchStepStatus.COMPLETED
        step.summary = report.get("summary")
        step.output_payload = report.get("output")
        step.completed_at = datetime.now(timezone.utc)
        step.duration_ms = duration_ms

        await self._messages.bulk_create(
            [
                AgentMessage(
                    run_id=self._run_id,
                    step_id=step.id,
                    sequence=self._next_message_sequence(),
                    role=AgentMessageRole(payload["role"]),
                    agent_name=payload["agent_name"],
                    content=payload["content"],
                    message_metadata=payload.get("metadata") or {},
                )
                for payload in update.get("messages", [])
            ]
        )
        # Commit per node: a later failure cannot erase completed steps.
        await self._session.commit()

    async def on_node_failure(
        self, node: str, error: BaseException, duration_ms: int, critical: bool
    ) -> None:
        """Close the step as failed, recording the error verbatim.

        Rolls back first: the exception may have come from a failed
        statement, leaving the session unusable for the write below.
        The `running` row was already committed by `on_node_start`, so
        the rollback discards nothing that matters.
        """
        await self._session.rollback()
        step = await self._current_step()
        if step is None:
            return

        message = f"{type(error).__name__}: {error}"
        step.status = ResearchStepStatus.FAILED
        step.summary = (
            f"{'Critical' if critical else 'Non-critical'} failure in '{node}'."
        )
        step.error_message = message
        step.completed_at = datetime.now(timezone.utc)
        step.duration_ms = duration_ms

        # The failure is part of the explainable trace, not only a log
        # line, so it is recorded in the transcript too.
        await self._messages.bulk_create(
            [
                AgentMessage(
                    run_id=self._run_id,
                    step_id=step.id,
                    sequence=self._next_message_sequence(),
                    role=AgentMessageRole.SYSTEM,
                    agent_name=node,
                    content=message,
                    message_metadata={"critical": critical, "node": node},
                )
            ]
        )
        await self._session.commit()

    async def _current_step(self) -> ResearchStep | None:
        """Re-fetch the step opened by `on_node_start`."""
        if self._current_step_id is None:
            return None
        return await self._session.get(ResearchStep, self._current_step_id)

    def _next_message_sequence(self) -> int:
        """Return the next transcript position and advance the counter."""
        sequence = self._message_sequence
        self._message_sequence += 1
        return sequence


def _elapsed_ms(monotonic_start: float) -> int:
    """Milliseconds elapsed since a monotonic start marker."""
    return int((time.monotonic() - monotonic_start) * 1000)


def _skip_reason(node: ResearchNode, run: ResearchRun) -> str:
    """Explain, per node, why it did not execute in this run.

    Distinguishes "the caller turned this source off" from "the planner
    included it but the router did not dispatch to it" — two very
    different situations that would otherwise look identical in the
    trace.
    """
    if node is ResearchNode.ASSET_RETRIEVAL and not run.include_assets:
        return "Knowledge base retrieval was not enabled for this run."
    if node is ResearchNode.WEB_RESEARCH and not run.include_web:
        return "External research was not enabled for this run."
    return "Not dispatched by the router for this run."
