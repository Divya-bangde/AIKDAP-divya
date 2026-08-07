"""Enumerations for the research module.

Lowercase values, matching the projects/assets/knowledge-base modules
(the tasks module uses uppercase; the majority convention wins here).
The graph's node names are deliberately *not* an enum in the database —
`research_steps.node_name` is a plain string so a future sprint can add
a node without a schema migration.
"""

import enum


class ResearchRunStatus(str, enum.Enum):
    """Lifecycle state of one research run.

    `PENDING` is the state a run is in between `POST /research/run`
    returning `201` and the Celery worker picking it up — the API
    always returns immediately, so callers observe this state.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchStepStatus(str, enum.Enum):
    """Execution state of a single graph node within a run.

    `SKIPPED` records a node that the plan named but the router did not
    dispatch to — the trace should show what was *considered*, not only
    what ran.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentMessageRole(str, enum.Enum):
    """Who produced a transcript entry.

    Mirrors the constitution's workflow roles rather than a chat
    protocol's roles: AIKDAP's agents communicate through shared graph
    state, not through a conversation.
    """

    SYSTEM = "system"
    PLANNER = "planner"
    ROUTER = "router"
    AGENT = "agent"
    TOOL = "tool"
    AGGREGATOR = "aggregator"
