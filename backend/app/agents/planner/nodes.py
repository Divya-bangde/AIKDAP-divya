"""Graph nodes and the strategy abstractions they execute against.

Two kinds of thing live here, in that order:

1. **Abstraction points** — `AssetRetriever`, `WebResearchProvider`,
   `Synthesizer` — plus the implementations shipped this sprint. These
   are where real semantic search, a real search API, and a real LLM
   are dropped in later. Every node depends on the abstract contract,
   never on a concrete implementation.
2. **The nodes themselves** — thin functions that resolve their
   dependencies from the graph config, call one strategy, and return a
   partial `ResearchState` update.

Nodes never write to the database and never commit. They emit `step`
and `messages` in their state update; `app.modules.research.service`
consumes the graph's update stream and persists those into
`research_steps` / `agent_messages`. That keeps the orchestration layer
free of transaction management and gives the Explainable-AI trace a
single writer.

`KnowledgeBaseAssetRetriever` is the one strategy that reads the
database. It does so through the existing repositories — a downward
dependency onto the data layer, not a dependency on another feature
module's service — and never opens a session or commits itself; the
caller injects the session-bound instance.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planner.planner import (
    PlannerStrategy,
    PlanRequest,
    ResearchPlan,
    extract_keywords,
    get_planner,
)
from app.agents.planner.prompts import (
    CONTEXT_BLOCK_TEMPLATE,
    render_planner_prompt,
    render_router_prompt,
    render_synthesis_prompt,
)
from app.agents.planner.state import (
    RETRIEVAL_NODES,
    AgentMessagePayload,
    ResearchNode,
    ResearchState,
    RetrievedDocument,
)
from app.core.logging.logger import get_logger
from app.modules.assets.repository import AssetRepository
from app.modules.knowledge_base.repository import KnowledgeChunkRepository

logger = get_logger(__name__)

#: How many chunks to pull from the knowledge base before ranking. A
#: bounded window keeps a large project from loading its entire corpus
#: into memory; a real vector index replaces both the window and the
#: keyword ranking below.
CANDIDATE_CHUNK_LIMIT = 500

#: Longest excerpt carried per evidence item. Long enough to be
#: quotable, short enough that the merged context stays readable.
SNIPPET_CHARACTERS = 700

#: Upper bound on the merged working context. Stands in for the token
#: budget a real model would impose.
MAX_CONTEXT_CHARACTERS = 12_000

#: Marks evidence that did not come from a real source, so nothing
#: downstream can mistake it for genuine data.
SIMULATED_SOURCE = "web"


# ---------------------------------------------------------------------------
# Abstraction points
# ---------------------------------------------------------------------------


class AssetRetriever(ABC):
    """Contract for retrieving evidence from a project's own assets.

    Integration point for semantic search: an implementation backed by
    ChromaDB (or pgvector) replaces the keyword ranking below without
    changing the node, the graph, or the API.
    """

    name: str = "abstract"

    @abstractmethod
    async def retrieve(
        self, *, project_id: uuid.UUID, query: str, limit: int
    ) -> list[RetrievedDocument]:
        """Return the most relevant evidence items for the query."""


class WebResearchProvider(ABC):
    """Contract for retrieving evidence from external sources.

    Integration point for a real search API. Implementations are
    expected to perform network I/O; nothing else in the graph does.
    """

    name: str = "abstract"

    @abstractmethod
    async def search(self, *, query: str, limit: int) -> list[RetrievedDocument]:
        """Return external evidence items for the query."""


class Synthesizer(ABC):
    """Contract for producing the final deliverable from evidence.

    Integration point for a real LLM. Implementations must ground the
    answer in the supplied documents and return the references they
    actually used.
    """

    name: str = "abstract"

    @abstractmethod
    async def synthesize(
        self,
        *,
        query: str,
        objective: str,
        context: str,
        documents: list[RetrievedDocument],
    ) -> tuple[str, list[str]]:
        """Return the final answer and the citation keys it relies on."""


# ---------------------------------------------------------------------------
# Implementations shipped this sprint
# ---------------------------------------------------------------------------


def relevance_score(text: str, keywords: list[str]) -> float:
    """Fraction of the query's keywords present in the text.

    Deliberately simple and explainable — it is a placeholder for
    vector similarity, and a score anyone can verify by eye is more
    useful than a fake one that merely looks sophisticated.
    """
    if not keywords:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for keyword in keywords if keyword in lowered)
    return round(hits / len(keywords), 4)


class KnowledgeBaseAssetRetriever(AssetRetriever):
    """Retrieves real chunks from the project's knowledge base, ranked by
    keyword overlap.

    The data is genuine — these are the chunks Sprint 6's processing
    pipeline produced from the user's uploaded assets. What is
    provisional is the *ranking*: keyword overlap, not embeddings,
    because no embedding provider exists yet
    (`app.modules.knowledge_base.embeddings.NullEmbeddingProvider`).
    Chunks with no keyword overlap are dropped rather than returned
    with a zero score: padding the context with irrelevant evidence
    would degrade the answer.
    """

    name = "knowledge_base_keyword_v1"

    def __init__(self, session: AsyncSession) -> None:
        self._chunks = KnowledgeChunkRepository(session)
        self._assets = AssetRepository(session)

    async def retrieve(
        self, *, project_id: uuid.UUID, query: str, limit: int
    ) -> list[RetrievedDocument]:
        """Rank the project's knowledge chunks against the query keywords."""
        keywords = extract_keywords(query)
        candidates = await self._chunks.list_by_project(
            project_id, limit=CANDIDATE_CHUNK_LIMIT
        )

        scored = [
            (relevance_score(chunk.content, keywords), chunk)
            for chunk in candidates
        ]
        relevant = sorted(
            (item for item in scored if item[0] > 0),
            key=lambda item: (-item[0], item[1].chunk_index),
        )[:limit]

        documents: list[RetrievedDocument] = []
        for score, chunk in relevant:
            asset = await self._assets.get_by_id(chunk.asset_id)
            title = asset.title if asset is not None else "Unknown asset"
            documents.append(
                RetrievedDocument(
                    source="asset",
                    reference=f"asset:{chunk.asset_id}#chunk-{chunk.chunk_index}",
                    title=f"{title} (chunk {chunk.chunk_index})",
                    snippet=_truncate(chunk.content, SNIPPET_CHARACTERS),
                    score=score,
                )
            )
        return documents


class MockWebResearchProvider(WebResearchProvider):
    """Deterministic stand-in for a real web search API.

    Performs no network I/O and invents no facts: every result states
    plainly that it is simulated, and its `reference` uses a `mock://`
    scheme so simulated evidence can never be mistaken for a real
    citation in a stored run. Deterministic so a re-run of the same
    query reproduces the same trace.
    """

    name = "mock_web_v1"

    async def search(self, *, query: str, limit: int) -> list[RetrievedDocument]:
        """Return `limit` clearly-labelled placeholder results."""
        keywords = extract_keywords(query, limit=limit) or ["general"]
        slug = "-".join(keywords[:3])

        documents: list[RetrievedDocument] = []
        for position in range(limit):
            keyword = keywords[position % len(keywords)]
            documents.append(
                RetrievedDocument(
                    source=SIMULATED_SOURCE,
                    reference=f"mock://web-research/{slug}/{position + 1}",
                    title=f"Simulated external reference on '{keyword}'",
                    snippet=(
                        "SIMULATED RESULT — no external search provider is configured "
                        f"for this deployment. A live provider would return material on "
                        f"'{keyword}' relevant to the request: {_truncate(query, 200)} "
                        "Treat this item as a placeholder, not as evidence."
                    ),
                    # Descending, so ordering is stable and simulated
                    # items never outrank real knowledge-base evidence.
                    score=round(max(0.05, 0.5 - position * 0.05), 4),
                )
            )
        return documents


class ExtractiveSynthesizer(Synthesizer):
    """Builds the deliverable by extracting from the retrieved evidence.

    Extractive rather than generative: every sentence in the answer is
    lifted from a real document and attributed. That makes it honest in
    the absence of an LLM — the output never contains a claim the
    evidence does not support — while producing a genuinely useful
    deliverable rather than a placeholder string.
    """

    name = "extractive_v1"

    async def synthesize(
        self,
        *,
        query: str,
        objective: str,
        context: str,
        documents: list[RetrievedDocument],
    ) -> tuple[str, list[str]]:
        """Assemble a cited answer from the highest-scoring evidence."""
        if not documents:
            answer = (
                f"## Objective\n{objective}\n\n"
                "## Result\nNo evidence could be retrieved for this request. "
                "The project's knowledge base returned no material matching the "
                "query, and no external research source is configured. Upload and "
                "process relevant assets, then re-run this research.\n"
            )
            return answer, []

        ranked = sorted(documents, key=lambda doc: -doc["score"])
        real = [doc for doc in ranked if doc["source"] != SIMULATED_SOURCE]
        simulated = [doc for doc in ranked if doc["source"] == SIMULATED_SOURCE]

        lines = ["## Objective", objective, "", "## Key findings"]
        if real:
            for position, document in enumerate(real, start=1):
                lines.append(
                    f"{position}. **{document['title']}** "
                    f"(relevance {document['score']:.2f}) — "
                    f"{_first_sentences(document['snippet'])} [{document['reference']}]"
                )
        else:
            lines.append(
                "1. No grounded evidence was available from the project's own assets; "
                "every item below is simulated and cannot support a factual claim."
            )

        if simulated:
            lines.extend(
                [
                    "",
                    "## Unverified placeholders",
                    (
                        f"{len(simulated)} external reference(s) were produced by the "
                        "simulated research provider and are excluded from the findings "
                        "above. They are recorded for traceability only."
                    ),
                ]
            )

        lines.extend(["", "## Sources"])
        for document in ranked:
            marker = " *(simulated)*" if document["source"] == SIMULATED_SOURCE else ""
            lines.append(f"- `{document['reference']}` — {document['title']}{marker}")

        citations = [document["reference"] for document in real]
        return "\n".join(lines), citations


@dataclass(frozen=True)
class GraphDependencies:
    """The strategies a single graph run executes against.

    Injected through the LangGraph config (`configurable.dependencies`)
    rather than imported by the nodes, so a run can be given a
    session-bound retriever, and tests can substitute fakes without
    patching module globals.
    """

    planner: PlannerStrategy
    asset_retriever: AssetRetriever
    web_provider: WebResearchProvider
    synthesizer: Synthesizer


def build_dependencies(session: AsyncSession) -> GraphDependencies:
    """Assemble the default dependency set for a database-backed run."""
    return GraphDependencies(
        planner=get_planner(),
        asset_retriever=KnowledgeBaseAssetRetriever(session),
        web_provider=MockWebResearchProvider(),
        synthesizer=ExtractiveSynthesizer(),
    )


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def planner_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    """Decompose the request into an execution plan.

    Writes `plan` and `objective`; every downstream node reads them.
    """
    dependencies = _dependencies(config)
    request = PlanRequest(
        query=state["query"],
        include_assets=state.get("include_assets", True),
        include_web=state.get("include_web", True),
        max_results=state.get("max_results", 5),
    )
    plan: ResearchPlan = await dependencies.planner.plan(request)
    prompt = render_planner_prompt(
        query=request.query,
        sources=[node.value for node in plan.retrieval_nodes],
        max_results=request.max_results,
    )

    logger.info(
        "research_node_planner",
        run_id=state.get("run_id"),
        strategy=plan.strategy,
        intent=plan.intent,
        step_count=len(plan.steps),
    )

    plan_payload = plan.model_dump(mode="json")
    return {
        "plan": plan_payload,
        "objective": plan.objective,
        "messages": [
            _message(
                role="planner",
                agent_name=dependencies.planner.name,
                content=f"{plan.objective}\n\n{plan.rationale}",
                metadata={"prompt": prompt, "intent": plan.intent, "keywords": plan.keywords},
            )
        ],
        "step": {
            "node": ResearchNode.PLANNER.value,
            "title": "Plan the research run",
            "summary": f"Classified as '{plan.intent}'; produced {len(plan.steps)} steps.",
            "output": plan_payload,
        },
    }


async def router_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    """Derive the retrieval route from the plan.

    The plan is authoritative: the router only translates it into an
    execution order, so replacing the planner changes routing without
    any change here.
    """
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    valid_nodes = {node.value for node in RETRIEVAL_NODES}
    route = [step["node"] for step in steps if step["node"] in valid_nodes]

    prompt = render_router_prompt(
        objective=state.get("objective", ""),
        steps=[f"{step['node']}: {step['title']}" for step in steps],
    )
    summary = (
        f"Routing to {', '.join(route)}." if route else "No retrieval source enabled."
    )

    logger.info("research_node_router", run_id=state.get("run_id"), route=route)

    return {
        "route": route,
        "messages": [
            _message(
                role="router",
                agent_name="router",
                content=summary,
                metadata={"prompt": prompt, "route": route},
            )
        ],
        "step": {
            "node": ResearchNode.ROUTER.value,
            "title": "Route to retrieval agents",
            "summary": summary,
            "output": {"route": route},
        },
    }


async def asset_retrieval_node(
    state: ResearchState, config: RunnableConfig
) -> dict[str, Any]:
    """Retrieve evidence from the project's own knowledge base."""
    dependencies = _dependencies(config)
    documents = await dependencies.asset_retriever.retrieve(
        project_id=uuid.UUID(state["project_id"]),
        query=state["query"],
        limit=state.get("max_results", 5),
    )
    summary = (
        f"Retrieved {len(documents)} knowledge-base chunk(s)."
        if documents
        else "No knowledge-base chunk matched the query."
    )

    logger.info(
        "research_node_asset_retrieval",
        run_id=state.get("run_id"),
        retriever=dependencies.asset_retriever.name,
        document_count=len(documents),
    )

    return {
        "documents": documents,
        "messages": [
            _message(
                role="agent",
                agent_name=dependencies.asset_retriever.name,
                content=summary,
                metadata={"references": [doc["reference"] for doc in documents]},
            )
        ],
        "step": {
            "node": ResearchNode.ASSET_RETRIEVAL.value,
            "title": "Search the project knowledge base",
            "summary": summary,
            "output": {"documents": documents},
        },
    }


async def web_research_node(
    state: ResearchState, config: RunnableConfig
) -> dict[str, Any]:
    """Retrieve external evidence (simulated in this sprint)."""
    dependencies = _dependencies(config)
    documents = await dependencies.web_provider.search(
        query=state["query"], limit=state.get("max_results", 5)
    )
    summary = (
        f"Produced {len(documents)} external reference(s) via "
        f"'{dependencies.web_provider.name}'."
    )

    logger.info(
        "research_node_web_research",
        run_id=state.get("run_id"),
        provider=dependencies.web_provider.name,
        document_count=len(documents),
    )

    return {
        "documents": documents,
        "messages": [
            _message(
                role="agent",
                agent_name=dependencies.web_provider.name,
                content=summary,
                metadata={
                    "references": [doc["reference"] for doc in documents],
                    "simulated": True,
                },
            )
        ],
        "step": {
            "node": ResearchNode.WEB_RESEARCH.value,
            "title": "Gather external references",
            "summary": summary,
            "output": {"documents": documents, "simulated": True},
        },
    }


async def context_builder_node(
    state: ResearchState, config: RunnableConfig
) -> dict[str, Any]:
    """Merge every retrieved item into one ranked, de-duplicated context.

    The join point of the graph: whichever retrieval nodes ran, this is
    where their output becomes a single artifact the synthesis step can
    be held accountable to.
    """
    documents = state.get("documents", [])

    seen: set[str] = set()
    unique: list[RetrievedDocument] = []
    for document in sorted(documents, key=lambda doc: -doc["score"]):
        if document["reference"] in seen:
            continue
        seen.add(document["reference"])
        unique.append(document)

    blocks: list[str] = []
    used = 0
    for document in unique:
        block = CONTEXT_BLOCK_TEMPLATE.format(**document)
        if used + len(block) > MAX_CONTEXT_CHARACTERS:
            break
        blocks.append(block)
        used += len(block)

    context = "\n\n".join(blocks)
    summary = (
        f"Merged {len(blocks)} of {len(documents)} item(s) into "
        f"{len(context)} characters of context."
    )

    logger.info(
        "research_node_context_builder",
        run_id=state.get("run_id"),
        included=len(blocks),
        received=len(documents),
        context_characters=len(context),
    )

    return {
        "context": context,
        "messages": [
            _message(
                role="aggregator",
                agent_name="context_builder",
                content=summary,
                metadata={"included_references": [doc["reference"] for doc in unique[: len(blocks)]]},
            )
        ],
        "step": {
            "node": ResearchNode.CONTEXT_BUILDER.value,
            "title": "Build the working context",
            "summary": summary,
            "output": {
                "context_characters": len(context),
                "included": len(blocks),
                "received": len(documents),
            },
        },
    }


async def synthesis_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    """Produce the final, cited deliverable."""
    dependencies = _dependencies(config)
    objective = state.get("objective", state["query"])
    context = state.get("context", "")
    documents = state.get("documents", [])

    answer, citations = await dependencies.synthesizer.synthesize(
        query=state["query"],
        objective=objective,
        context=context,
        documents=documents,
    )
    prompt = render_synthesis_prompt(
        objective=objective, query=state["query"], context=context
    )
    summary = f"Synthesized the deliverable from {len(citations)} grounded citation(s)."

    logger.info(
        "research_node_synthesis",
        run_id=state.get("run_id"),
        synthesizer=dependencies.synthesizer.name,
        citation_count=len(citations),
        answer_characters=len(answer),
    )

    return {
        "final_answer": answer,
        "citations": citations,
        "messages": [
            _message(
                role="aggregator",
                agent_name=dependencies.synthesizer.name,
                content=answer,
                metadata={"prompt": prompt, "citations": citations},
            )
        ],
        "step": {
            "node": ResearchNode.SYNTHESIS.value,
            "title": "Synthesize the deliverable",
            "summary": summary,
            "output": {"citations": citations, "answer_characters": len(answer)},
        },
    }


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------


def route_after_router(state: ResearchState) -> str:
    """Dispatch to the first retrieval node on the route, if any.

    Retrieval nodes run in sequence rather than in parallel: they share
    one database session, and a deterministic order keeps the stored
    step trace reproducible.
    """
    route = state.get("route", [])
    if ResearchNode.ASSET_RETRIEVAL.value in route:
        return ResearchNode.ASSET_RETRIEVAL.value
    if ResearchNode.WEB_RESEARCH.value in route:
        return ResearchNode.WEB_RESEARCH.value
    return ResearchNode.CONTEXT_BUILDER.value


def route_after_asset_retrieval(state: ResearchState) -> str:
    """Continue to web research if it is on the route, else merge context."""
    if ResearchNode.WEB_RESEARCH.value in state.get("route", []):
        return ResearchNode.WEB_RESEARCH.value
    return ResearchNode.CONTEXT_BUILDER.value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dependencies(config: RunnableConfig) -> GraphDependencies:
    """Extract the injected dependency container from the graph config."""
    dependencies = (config.get("configurable") or {}).get("dependencies")
    if not isinstance(dependencies, GraphDependencies):
        raise RuntimeError(
            "Research graph invoked without a GraphDependencies instance in "
            "config['configurable']['dependencies']."
        )
    return dependencies


def _message(
    *, role: str, agent_name: str, content: str, metadata: dict[str, Any]
) -> AgentMessagePayload:
    """Build one transcript entry for the Explainable-AI record."""
    return AgentMessagePayload(
        role=role, agent_name=agent_name, content=content, metadata=metadata
    )


def _truncate(text: str, limit: int) -> str:
    """Collapse whitespace and cut to `limit` characters on a word boundary."""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    cut = normalized[:limit].rsplit(" ", 1)[0]
    return f"{cut}..."


def _first_sentences(text: str, *, count: int = 2) -> str:
    """Return the leading sentences of an excerpt, for the findings list."""
    sentences = [part.strip() for part in text.replace("\n", " ").split(". ") if part.strip()]
    if not sentences:
        return text
    selected = ". ".join(sentences[:count]).rstrip(".")
    return f"{selected}."
