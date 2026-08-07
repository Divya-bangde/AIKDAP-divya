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

from app.agents.planner.graph import get_research_graph
from app.agents.planner.nodes import build_dependencies
from app.agents.planner.state import ResearchNode
from app.core.logging.logger import get_logger
from app.modules.projects.repository import ProjectRepository
from app.modules.research.enums import (
    AgentMessageRole,
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

    Consumes the graph's update stream rather than awaiting a single
    result, so each node's output is persisted the moment it completes.
    A run that fails halfway therefore still carries a complete record
    of everything that succeeded before it.

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

        started_at = datetime.now(timezone.utc)
        run.status = ResearchRunStatus.RUNNING
        run.started_at = started_at
        run.error_message = None
        await self._session.commit()

        logger.info("research_run_started", run_id=str(run.id), query=run.query)

        monotonic_start = time.monotonic()
        cursor = ExecutionCursor(monotonic_start)
        final_state: dict[str, Any] = {}

        try:
            async for node_name, delta in self._stream(run):
                await self._record_step(run, node_name, delta, cursor)
                _absorb(final_state, delta)
        except Exception as exc:  # noqa: BLE001 - recorded on the run, not swallowed
            # The graph may have failed mid-statement; roll back before
            # writing the failure or the commit below fails too.
            await self._session.rollback()
            await self._fail(run_id, monotonic_start, exc)
            return

        await self._record_skipped(run, cursor)
        await self._complete(run, monotonic_start, final_state)

    async def _stream(self, run: ResearchRun):
        """Yield `(node_name, state_delta)` for each node as it completes."""
        graph = get_research_graph()
        initial_state = {
            "run_id": str(run.id),
            "project_id": str(run.project_id),
            "owner_id": str(run.owner_id),
            "query": run.query,
            "include_assets": run.include_assets,
            "include_web": run.include_web,
            "max_results": run.max_results,
        }
        config = {"configurable": {"dependencies": build_dependencies(self._session)}}

        async for update in graph.astream(
            initial_state, config=config, stream_mode="updates"
        ):
            for node_name, delta in update.items():
                yield node_name, delta

    async def _record_step(
        self,
        run: ResearchRun,
        node_name: str,
        delta: dict[str, Any],
        cursor: "ExecutionCursor",
    ) -> None:
        """Persist one completed node as a step plus its transcript entries."""
        report = delta.get("step") or {}
        completed_at = datetime.now(timezone.utc)
        duration_ms = cursor.elapsed_ms()

        step = await self._steps.create(
            ResearchStep(
                run_id=run.id,
                step_index=cursor.next_step_index(),
                node_name=node_name,
                title=report.get("title", node_name),
                status=ResearchStepStatus.COMPLETED,
                summary=report.get("summary"),
                output_payload=report.get("output"),
                started_at=cursor.step_started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )
        )

        await self._messages.bulk_create(
            [
                AgentMessage(
                    run_id=run.id,
                    step_id=step.id,
                    sequence=cursor.next_message_sequence(),
                    role=AgentMessageRole(payload["role"]),
                    agent_name=payload["agent_name"],
                    content=payload["content"],
                    message_metadata=payload.get("metadata") or {},
                )
                for payload in delta.get("messages", [])
            ]
        )

        # Commit per node: a run still executing is observable through
        # the API, and a later failure cannot erase completed steps.
        await self._session.commit()
        cursor.close_step(completed_at)
        cursor.record_execution(node_name)

        logger.info(
            "research_step_recorded",
            run_id=str(run.id),
            node=node_name,
            step_index=step.step_index,
            duration_ms=duration_ms,
        )

    async def _record_skipped(self, run: ResearchRun, cursor: "ExecutionCursor") -> None:
        """Record the nodes that never ran, and why.

        A trace that only shows what executed hides the decision that
        mattered; the constitution requires routing itself to be
        explainable.
        """
        skipped = [
            node for node in ResearchNode if node.value not in cursor.executed_nodes
        ]
        for node in skipped:
            await self._steps.create(
                ResearchStep(
                    run_id=run.id,
                    step_index=cursor.next_step_index(),
                    node_name=node.value,
                    title=f"Skipped: {node.value}",
                    status=ResearchStepStatus.SKIPPED,
                    summary=_skip_reason(node, run),
                    started_at=None,
                    completed_at=None,
                    duration_ms=None,
                )
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
        run.completed_at = datetime.now(timezone.utc)
        run.duration_ms = _elapsed_ms(monotonic_start)
        await self._session.commit()

        logger.info(
            "research_run_completed",
            run_id=str(run.id),
            duration_ms=run.duration_ms,
            citation_count=len(run.citations or []),
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


class ExecutionCursor:
    """Tracks ordering and per-step timing across one run's stream.

    Kept as a small object rather than a handful of loop variables so
    `_record_step` stays a single-responsibility method and the timing
    rule lives in one place: a step's duration is the wall time since
    the previous step closed (or since the run started, for the first).
    """

    def __init__(self, monotonic_start: float) -> None:
        self._monotonic_start = monotonic_start
        self._boundary = monotonic_start
        self._step_index = 0
        self._message_sequence = 0
        self.step_started_at: datetime = datetime.now(timezone.utc)
        self.executed_nodes: list[str] = []

    def next_step_index(self) -> int:
        """Return the next step position and advance the counter."""
        index = self._step_index
        self._step_index += 1
        return index

    def next_message_sequence(self) -> int:
        """Return the next transcript position and advance the counter."""
        sequence = self._message_sequence
        self._message_sequence += 1
        return sequence

    def elapsed_ms(self) -> int:
        """Milliseconds spent in the step currently being closed."""
        return int((time.monotonic() - self._boundary) * 1000)

    def close_step(self, completed_at: datetime) -> None:
        """Move the timing boundary to the end of the step just recorded."""
        self._boundary = time.monotonic()
        self.step_started_at = completed_at

    def record_execution(self, node_name: str) -> None:
        """Note that a node actually ran."""
        self.executed_nodes.append(node_name)


def _absorb(final_state: dict[str, Any], delta: dict[str, Any]) -> None:
    """Accumulate the scalar fields the run needs from a node's update.

    Only last-write-wins fields are carried: the additive channels
    (`documents`, `messages`) are consumed as they stream and are not
    needed again once persisted.
    """
    for field in ("plan", "objective", "final_answer", "citations", "context"):
        if field in delta:
            final_state[field] = delta[field]


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
