"""The LangGraph orchestrator: builds and compiles the research workflow.

Responsibilities are deliberately narrow — graph construction, node
registration, conditional transitions, and compilation. No agent
business logic lives here; every node comes from `AGENT_REGISTRY` and
is wrapped by `tracking.instrument` so execution tracking and the
failure policy are applied uniformly rather than reimplemented per
agent.

Topology::

    START
      -> planner
      -> router
           |-- asset_retrieval --+-> web_research --+
           |                     \\-----------------|--> context_builder
           |-- web_research ---------------------- |
           \\--------------------------------------+
      -> context_builder
      -> synthesis
      -> END

Retrieval agents are chained conditionally rather than fanned out in
parallel. Both are valid LangGraph, but they share a single database
session and the run's step trace is persisted in execution order —
sequencing keeps both deterministic. Fan-out remains available:
`retrieved_documents` and `intermediate_results` already carry
reducers, so parallel branches would merge correctly if a future sprint
needs the latency win.

The compiled graph holds no per-run state. Strategies, the database
session, and the execution tracker are injected per invocation through
`config["configurable"]`, so one compiled instance is safely shared
across concurrent runs.
"""

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.planner.nodes import (
    route_after_asset_retrieval,
    route_after_router,
)
from app.agents.planner.registry import AGENT_REGISTRY, get_node_spec
from app.agents.planner.state import ResearchNode, ResearchState
from app.agents.planner.tracking import instrument


def build_research_graph() -> StateGraph:
    """Construct the uncompiled research graph from the agent registry.

    Separate from `get_research_graph` so tests (and any future variant
    needing a checkpointer or an interrupt) can compile the same
    topology with different options.
    """
    builder: StateGraph = StateGraph(ResearchState)

    # Nodes come from the registry, so registering an agent is enough
    # to make it available here — only its edges remain an explicit
    # decision below.
    for name, spec in AGENT_REGISTRY.items():
        builder.add_node(name, instrument(spec))

    builder.add_edge(START, ResearchNode.PLANNER.value)
    builder.add_edge(ResearchNode.PLANNER.value, ResearchNode.ROUTER.value)

    # The router dispatches to the first selected retrieval agent, or
    # skips straight to context building when none was selected.
    builder.add_conditional_edges(
        ResearchNode.ROUTER.value,
        route_after_router,
        {
            ResearchNode.ASSET_RETRIEVAL.value: ResearchNode.ASSET_RETRIEVAL.value,
            ResearchNode.WEB_RESEARCH.value: ResearchNode.WEB_RESEARCH.value,
            ResearchNode.CONTEXT_BUILDER.value: ResearchNode.CONTEXT_BUILDER.value,
        },
    )
    builder.add_conditional_edges(
        ResearchNode.ASSET_RETRIEVAL.value,
        route_after_asset_retrieval,
        {
            ResearchNode.WEB_RESEARCH.value: ResearchNode.WEB_RESEARCH.value,
            ResearchNode.CONTEXT_BUILDER.value: ResearchNode.CONTEXT_BUILDER.value,
        },
    )

    builder.add_edge(ResearchNode.WEB_RESEARCH.value, ResearchNode.CONTEXT_BUILDER.value)
    builder.add_edge(ResearchNode.CONTEXT_BUILDER.value, ResearchNode.SYNTHESIS.value)
    builder.add_edge(ResearchNode.SYNTHESIS.value, END)

    return builder


@lru_cache(maxsize=1)
def get_research_graph() -> CompiledStateGraph:
    """Return the process-wide compiled research graph.

    Compiled once and reused: compilation validates the topology and is
    pure overhead to repeat per request. Safe to cache because the
    compiled graph carries no run-specific state.
    """
    return build_research_graph().compile()


def workflow_node_order() -> list[str]:
    """The registered agents in graph order.

    Used by the execution service to record agents that never ran as
    `skipped`, so a trace never silently omits a node.
    """
    return [spec.name for spec in (get_node_spec(name) for name in AGENT_REGISTRY)]
