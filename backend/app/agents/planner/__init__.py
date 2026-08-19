"""Planner Agent and the LangGraph research orchestration workflow.

Public surface for consumers (currently `app.modules.research`):

- `get_research_graph()` — the compiled workflow to execute.
- `build_dependencies(session)` — the strategy container to inject.
- `ResearchNode` / `ResearchState` — the node names and state contract.

Everything else is an implementation detail of the graph.
"""

from app.agents.planner.graph import (
    build_research_graph,
    get_research_graph,
    workflow_node_order,
)
from app.agents.planner.nodes import (
    AssetRetriever,
    GraphDependencies,
    SemanticAssetRetriever,
    WebResearchProvider,
    build_citation,
    build_dependencies,
)
from app.agents.planner.planner import (
    PlannerStrategy,
    PlanRequest,
    ResearchPlan,
    get_planner,
)
from app.agents.planner.registry import (
    AGENT_REGISTRY,
    NodeSpec,
    get_node_spec,
    register_agent,
    registered_agents,
    retrieval_agents,
)
from app.agents.planner.state import Citation, ResearchNode, ResearchState
from app.agents.planner.synthesis import (
    ExtractiveSynthesizer,
    GroundedSynthesizer,
    SynthesisResponseError,
    SynthesisResult,
    Synthesizer,
    get_synthesizer,
)
from app.agents.planner.tracking import (
    NodeExecutionTracker,
    NullTracker,
    instrument,
)

__all__ = [
    "AGENT_REGISTRY",
    "AssetRetriever",
    "Citation",
    "ExtractiveSynthesizer",
    "GraphDependencies",
    "GroundedSynthesizer",
    "NodeExecutionTracker",
    "NodeSpec",
    "NullTracker",
    "PlanRequest",
    "PlannerStrategy",
    "ResearchNode",
    "ResearchPlan",
    "ResearchState",
    "SemanticAssetRetriever",
    "SynthesisResponseError",
    "SynthesisResult",
    "Synthesizer",
    "WebResearchProvider",
    "build_citation",
    "build_dependencies",
    "build_research_graph",
    "get_node_spec",
    "get_planner",
    "get_research_graph",
    "get_synthesizer",
    "instrument",
    "register_agent",
    "registered_agents",
    "retrieval_agents",
    "workflow_node_order",
]
