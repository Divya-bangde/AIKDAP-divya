"""Assembly of the research LangGraph workflow.

Topology (frozen for this sprint)::

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

Retrieval nodes are chained conditionally rather than fanned out in
parallel. Both would be valid LangGraph, but they share a single
database session and the run's step trace is persisted in execution
order — sequencing keeps both deterministic. The fan-out version stays
available: `ResearchState.documents` already uses an additive reducer,
so parallel branches would merge correctly if a future sprint needs the
latency win.

The compiled graph holds no per-run state: strategies and the database
session are injected per invocation via
`config["configurable"]["dependencies"]`, so one compiled instance is
safely shared across concurrent runs.
"""

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.planner.nodes import (
    asset_retrieval_node,
    context_builder_node,
    planner_node,
    route_after_asset_retrieval,
    route_after_router,
    router_node,
    synthesis_node,
    web_research_node,
)
from app.agents.planner.state import ResearchNode, ResearchState


def build_research_graph() -> StateGraph:
    """Construct the uncompiled research graph.

    Separate from `get_research_graph` so tests (and any future variant
    that needs a checkpointer or an interrupt) can compile the same
    topology with different options.
    """
    builder: StateGraph = StateGraph(ResearchState)

    builder.add_node(ResearchNode.PLANNER.value, planner_node)
    builder.add_node(ResearchNode.ROUTER.value, router_node)
    builder.add_node(ResearchNode.ASSET_RETRIEVAL.value, asset_retrieval_node)
    builder.add_node(ResearchNode.WEB_RESEARCH.value, web_research_node)
    builder.add_node(ResearchNode.CONTEXT_BUILDER.value, context_builder_node)
    builder.add_node(ResearchNode.SYNTHESIS.value, synthesis_node)

    builder.add_edge(START, ResearchNode.PLANNER.value)
    builder.add_edge(ResearchNode.PLANNER.value, ResearchNode.ROUTER.value)

    # The router picks the first enabled retrieval source, or skips
    # straight to context building when none is enabled.
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
