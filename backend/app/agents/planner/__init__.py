"""Planner Agent and the LangGraph research orchestration workflow.

Public surface for consumers (currently `app.modules.research`):

- `get_research_graph()` — the compiled workflow to execute.
- `build_dependencies(session)` — the strategy container to inject.
- `ResearchNode` / `ResearchState` — the node names and state contract.

Everything else is an implementation detail of the graph.
"""

from app.agents.planner.graph import build_research_graph, get_research_graph
from app.agents.planner.nodes import (
    AssetRetriever,
    GraphDependencies,
    Synthesizer,
    WebResearchProvider,
    build_dependencies,
)
from app.agents.planner.planner import (
    PlannerStrategy,
    PlanRequest,
    ResearchPlan,
    get_planner,
)
from app.agents.planner.state import ResearchNode, ResearchState

__all__ = [
    "AssetRetriever",
    "GraphDependencies",
    "PlanRequest",
    "PlannerStrategy",
    "ResearchNode",
    "ResearchPlan",
    "ResearchState",
    "Synthesizer",
    "WebResearchProvider",
    "build_dependencies",
    "build_research_graph",
    "get_planner",
    "get_research_graph",
]
