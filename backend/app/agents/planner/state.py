"""Shared state contract for the research LangGraph workflow.

`ResearchState` is the single channel every node reads from and writes
to. Per the engineering constitution, agents never call each other
directly — a node's only output is a partial state update, and the
graph decides who runs next. Everything here is JSON-serializable so
the same structures can be persisted verbatim into the `research_runs`,
`research_steps`, and `agent_messages` tables without a translation
layer.

Two channels use `operator.add` reducers (`documents`, `messages`):
each node *appends* to them rather than replacing them, so retrieval
results and the agent transcript accumulate across the run. Every other
channel is last-write-wins, which is what the sequential planner ->
router -> ... -> synthesis flow expects.
"""

import enum
import operator
from typing import Annotated, Any, TypedDict


class ResearchNode(str, enum.Enum):
    """Canonical node names for the research graph.

    Owned here rather than in `app.modules.research` because the graph
    defines its own topology; the research module persists these values
    as plain strings (`research_steps.node_name`) so adding a node in a
    future sprint never requires a database migration.
    """

    PLANNER = "planner"
    ROUTER = "router"
    ASSET_RETRIEVAL = "asset_retrieval"
    WEB_RESEARCH = "web_research"
    CONTEXT_BUILDER = "context_builder"
    SYNTHESIS = "synthesis"


#: Nodes the router may dispatch to. Used by the planner to build the
#: plan and by the router to derive the execution route.
RETRIEVAL_NODES: tuple[ResearchNode, ...] = (
    ResearchNode.ASSET_RETRIEVAL,
    ResearchNode.WEB_RESEARCH,
)


class PlannedStep(TypedDict):
    """One entry in the planner's execution plan."""

    index: int
    node: str
    title: str
    description: str


class RetrievedDocument(TypedDict):
    """A single retrieved evidence item, from any source.

    `reference` is the citation key carried through to the synthesized
    answer, so it must be stable and uniquely identify the origin
    (e.g. `asset:<uuid>#chunk-3`, `mock://web-research/...`).
    """

    source: str
    reference: str
    title: str
    snippet: str
    score: float


class AgentMessagePayload(TypedDict):
    """A transcript entry emitted by a node.

    Persisted as one `agent_messages` row. This is the Explainable-AI
    record of *what each agent said and why*, distinct from the
    structural step record below.
    """

    role: str
    agent_name: str
    content: str
    metadata: dict[str, Any]


class StepRecord(TypedDict):
    """A node's structural report of its own execution.

    Persisted as one `research_steps` row. Overwritten by each node
    rather than accumulated: the execution service reads it from that
    node's individual stream update, so no history is lost.
    """

    node: str
    title: str
    summary: str
    output: dict[str, Any]


class ResearchState(TypedDict, total=False):
    """The graph's shared state channel.

    `total=False` because nodes contribute their own slices; only the
    input fields are guaranteed present when the graph starts.
    """

    # --- Inputs, set by the caller before the graph starts ---
    run_id: str
    project_id: str
    owner_id: str
    query: str
    include_assets: bool
    include_web: bool
    max_results: int

    # --- Planner node output ---
    plan: dict[str, Any]
    objective: str

    # --- Router node output ---
    route: list[str]

    # --- Retrieval node output (accumulated across sources) ---
    documents: Annotated[list[RetrievedDocument], operator.add]

    # --- Context builder output ---
    context: str

    # --- Synthesis node output ---
    final_answer: str
    citations: list[str]

    # --- Cross-cutting observability ---
    messages: Annotated[list[AgentMessagePayload], operator.add]
    step: StepRecord
