"""Graph nodes and the strategy abstractions they execute against.

Two kinds of thing live here, in that order:

1. **Abstraction points** — `AssetRetriever` and `WebResearchProvider`,
   plus the implementations they resolve to. `Synthesizer` lives in
   `synthesis.py` alongside its two real implementations. Every node
   depends on the abstract contract, never on a concrete one.
2. **The nodes themselves** — thin functions that resolve their
   dependencies from the graph config, call one strategy, and return a
   partial `ResearchState` update.

Nodes never write to the database and never commit. They emit `step`
and `messages` in their state update; `app.modules.research.service`
consumes the graph's update stream and persists those into
`research_steps` / `agent_messages`. That keeps the orchestration layer
free of transaction management and gives the Explainable-AI trace a
single writer.

`SemanticAssetRetriever` is the one strategy that reads the database.
It does so through the knowledge base's own service — the two-stage
retrieval built in Sprints 9C/9D — rather than reimplementing ranking
here, and never opens a session or commits itself; the caller injects
the session-bound instance.
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
    PROVENANCE_KEYS,
    RETRIEVAL_NODES,
    AgentMessagePayload,
    Citation,
    ResearchNode,
    ResearchState,
    RetrievedDocument,
    degraded_warnings,
)

# `Synthesizer` and its implementations live in their own module; they
# are imported (not re-declared) here because `GraphDependencies` and
# the synthesis node need them. The dependency runs one way —
# `nodes -> synthesis` — mirroring `nodes -> planner`.
from app.agents.planner.synthesis import (  # noqa: F401 - re-exported for callers
    ExtractiveSynthesizer,
    GroundedSynthesizer,
    SynthesisResult,
    Synthesizer,
    get_synthesizer,
)
from app.core.logging.logger import get_logger
from app.modules.assets.repository import AssetRepository
from app.modules.knowledge_base.service import KnowledgeBaseService

# The state's `status` field mirrors the persisted run status, so the
# vocabulary is taken from the existing enum rather than duplicated
# here. `enums` is a dependency-free leaf module, so importing it
# introduces no cycle.
from app.modules.research.enums import ResearchRunStatus

logger = get_logger(__name__)

#: Longest excerpt carried per evidence item. Long enough to be
#: quotable, short enough that the merged context stays readable.
SNIPPET_CHARACTERS = 700

#: How many candidates stage 1 retrieves per requested result. The
#: reranker needs a pool wider than the final answer set to reorder;
#: `max_results` is what the caller asked to *see*, not what retrieval
#: should consider.
CANDIDATE_MULTIPLIER = 4

#: Upper bound on the merged working context. Stands in for the token
#: budget a real model would impose.
MAX_CONTEXT_CHARACTERS = 12_000

#: Source label for external evidence. Whether that evidence is real is
#: carried per-document on `RetrievedDocument.simulated`, not inferred
#: from this string — inferring it here is what previously caused every
#: web reference to be dropped from the citation list.
WEB_SOURCE = "web"

#: Source label for evidence from the project's own knowledge base.
ASSET_SOURCE = "asset"


# ---------------------------------------------------------------------------
# Abstraction points
# ---------------------------------------------------------------------------


class AssetRetriever(ABC):
    """Contract for retrieving evidence from a project's own assets.

    `owner_id` is part of the contract rather than something the caller
    filters on afterwards: an implementation must scope its *query* to
    the owner, so evidence the caller does not own is never loaded, let
    alone sent to a model. Retrieving broadly and filtering later is
    the failure mode this signature exists to prevent.
    """

    name: str = "abstract"

    @abstractmethod
    async def retrieve(
        self, *, owner_id: uuid.UUID, project_id: uuid.UUID, query: str, limit: int
    ) -> list[RetrievedDocument]:
        """Return the most relevant evidence items the owner may see."""


class WebResearchProvider(ABC):
    """Contract for retrieving evidence from external sources.

    Integration point for a real search API. Implementations are
    expected to perform network I/O; nothing else in the graph does.
    """

    name: str = "abstract"

    @abstractmethod
    async def search(self, *, query: str, limit: int) -> list[RetrievedDocument]:
        """Return external evidence items for the query."""


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


def build_citation(document: RetrievedDocument, position: int) -> Citation:
    """Derive a structured citation from a retrieved document.

    Every field is read defensively: a retriever added in a future
    sprint (or a partially-populated document from an external API)
    must not be able to crash the run by omitting metadata. Missing
    values degrade to explicit "unknown" markers rather than being
    invented — an absent URL stays absent.

    `simulated` defaults to `True` when a document does not say: an
    unlabelled item is treated as unverified, never as trustworthy.

    Optional provenance (`chunk_id`, `asset_id`, the retrieval and
    rerank scores) is copied through only when the document carries it,
    so a citation from a knowledge chunk stays traceable to that exact
    row while one from a source with no such identity is not padded
    with nulls that would imply an identity it lacks.
    """
    citation = Citation(
        id=f"c{position}",
        reference=document.get("reference") or "",
        title=document.get("title") or "Untitled reference",
        source=document.get("source") or "unknown",
        provider=document.get("provider") or "unknown",
        snippet=document.get("snippet") or "",
        score=float(document.get("score") or 0.0),
        simulated=bool(document.get("simulated", True)),
    )
    for key in PROVENANCE_KEYS:
        if key in document:
            citation[key] = document[key]  # type: ignore[literal-required]
    return citation


class SemanticAssetRetriever(AssetRetriever):
    """Retrieves evidence through the knowledge base's two-stage search.

    Delegates to `KnowledgeBaseService.two_stage_search` rather than
    ranking here: stage 1 (BGE-M3 embeddings + pgvector, Sprint 9C) and
    stage 2 (cross-encoder reranking, Sprint 9D) already exist, are
    tested, and enforce ownership in the query itself. Reimplementing
    any of that in the research graph would be a second retrieval path
    to keep in sync.

    Ownership travels into the search, not around it: the service
    validates the project against `owner_id` and the repository joins
    on it, so a chunk belonging to another user is never a candidate —
    and therefore can never reach the synthesis model.

    Whether reranking actually ran is recorded on every document it
    returns. When the reranker is unavailable (see
    `app.modules.knowledge_base.reranking`), stage 1's results are used
    as-is; nothing here substitutes another model or invents a rerank
    score.
    """

    name = "knowledge_base_semantic_v1"

    def __init__(self, session: AsyncSession) -> None:
        self._service = KnowledgeBaseService(session)
        self._assets = AssetRepository(session)

    async def retrieve(
        self, *, owner_id: uuid.UUID, project_id: uuid.UUID, query: str, limit: int
    ) -> list[RetrievedDocument]:
        """Return the owner's most relevant chunks, best first."""
        outcome = await self._service.two_stage_search(
            owner_id,
            query=query,
            project_id=project_id,
            # Over-retrieve so stage 2 has a pool to reorder. `limit` is
            # what the caller wants to see, not what retrieval should
            # consider.
            candidate_k=limit * CANDIDATE_MULTIPLIER,
            top_k=limit,
        )

        logger.info(
            "research_semantic_retrieval",
            project_id=str(project_id),
            candidate_count=outcome.candidate_count,
            result_count=len(outcome.hits),
            reranking_status=outcome.reranking_status.value,
            reranker_model=outcome.reranker_model,
            # The gate's decision is part of the run's explanation: a
            # research run with no answer must be able to show that
            # evidence was retrieved and then rejected, rather than
            # looking as though nothing was found.
            rejected_count=len(outcome.rejected_hits),
            relevance_threshold=outcome.relevance_threshold,
        )

        documents: list[RetrievedDocument] = []
        for rank, hit in enumerate(outcome.hits, start=1):
            asset = await self._assets.get_by_id(hit.chunk.asset_id)
            title = asset.title if asset is not None else "Unknown asset"
            document = RetrievedDocument(
                source=ASSET_SOURCE,
                provider=self.name,
                reference=f"asset:{hit.chunk.asset_id}#chunk-{hit.chunk.chunk_index}",
                title=f"{title} (chunk {hit.chunk.chunk_index})",
                snippet=_truncate(hit.chunk.content, SNIPPET_CHARACTERS),
                # `score` is the one cross-source comparable number the
                # context builder ranks on. The two stage-specific
                # scores are preserved separately below, unmodified.
                score=round(1.0 - hit.retrieval_distance, 4),
                simulated=False,
                chunk_id=str(hit.chunk.id),
                asset_id=str(hit.chunk.asset_id),
                rank=rank,
                retrieval_rank=hit.retrieval_rank,
                retrieval_score=round(1.0 - hit.retrieval_distance, 6),
                reranking_status=outcome.reranking_status.value,
            )
            # Records the bar this chunk had to clear, so a stored
            # citation says not just "this was retrieved" but "this was
            # judged relevant, at this threshold".
            if outcome.relevance_threshold is not None:
                document["relevance_threshold"] = outcome.relevance_threshold
            if asset is not None:
                document["file_name"] = asset.file_name
            # Absent, not zero, when stage 2 did not run: a missing
            # measurement must not read as a low one.
            if hit.rerank_score is not None:
                document["rerank_score"] = hit.rerank_score
            documents.append(document)
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
                    source=WEB_SOURCE,
                    provider=self.name,
                    reference=f"mock://web-research/{slug}/{position + 1}",
                    title=f"Simulated external reference on '{keyword}'",
                    simulated=True,
                    snippet=(
                        "SIMULATED RESULT — no external search provider is configured "
                        f"for this deployment. A live provider would return material on "
                        f"'{keyword}' relevant to the request: {_truncate(query, 200)} "
                        "Treat this item as a placeholder, not as evidence."
                    ),
                    # Descending, so ordering within this provider's own
                    # results is stable.
                    score=round(max(0.05, 0.5 - position * 0.05), 4),
                    # The provider's own final ordering. The context
                    # builder merges by this, so a retriever's ranking
                    # survives the merge rather than being re-derived
                    # from a score that is not comparable across
                    # sources.
                    rank=position + 1,
                )
            )
        return documents


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
        asset_retriever=SemanticAssetRetriever(session),
        web_provider=MockWebResearchProvider(),
        synthesizer=get_synthesizer(),
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
    # Only routable retrieval agents named by the plan are selected, so
    # an unknown node in a plan can never cause the graph to dispatch
    # to it. `RETRIEVAL_NODES` is the single source of truth for what
    # is routable; the registry reads the same list.
    routable = [node.value for node in RETRIEVAL_NODES]
    selected = [step["node"] for step in steps if step["node"] in routable]
    skipped = [name for name in routable if name not in selected]

    prompt = render_router_prompt(
        objective=state.get("objective", ""),
        steps=[f"{step['node']}: {step['title']}" for step in steps],
    )
    summary = (
        f"Routing to {', '.join(selected)}."
        if selected
        else "No retrieval source enabled."
    )

    logger.info(
        "research_node_router",
        run_id=state.get("run_id"),
        selected_agents=selected,
        skipped_agents=skipped,
    )

    return {
        "selected_agents": selected,
        "messages": [
            _message(
                role="router",
                agent_name="router",
                content=summary,
                metadata={"selected_agents": selected, "skipped_agents": skipped, "prompt": prompt},
            )
        ],
        "step": {
            "node": ResearchNode.ROUTER.value,
            "title": "Route to retrieval agents",
            "summary": summary,
            "output": {"selected_agents": selected, "skipped_agents": skipped},
        },
    }


async def asset_retrieval_node(
    state: ResearchState, config: RunnableConfig
) -> dict[str, Any]:
    """Retrieve evidence from the project's own knowledge base.

    Scoped to the run's owner, not merely to its project: the owner is
    carried in the shared state and passed into the retriever, so the
    search itself is restricted rather than its results being filtered
    afterwards.
    """
    dependencies = _dependencies(config)
    documents = await dependencies.asset_retriever.retrieve(
        owner_id=uuid.UUID(state["owner_id"]),
        project_id=uuid.UUID(state["project_id"]),
        query=state["query"],
        limit=state.get("max_results", 5),
    )
    # Every document from one search shares the same status, so the
    # first one is representative; absent when nothing was retrieved.
    reranking_status = documents[0].get("reranking_status") if documents else None
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
        reranking_status=reranking_status,
    )

    return {
        "retrieved_documents": documents,
        "messages": [
            _message(
                role="agent",
                agent_name=dependencies.asset_retriever.name,
                content=summary,
                metadata={
                    "references": [doc["reference"] for doc in documents],
                    "reranking_status": reranking_status,
                },
            )
        ],
        "step": {
            "node": ResearchNode.ASSET_RETRIEVAL.value,
            "title": "Search the project knowledge base",
            "summary": summary,
            "output": {
                "documents": documents,
                "document_count": len(documents),
                "references": [doc.get("reference") for doc in documents],
                # Recorded on the step so the trace shows whether stage
                # 2 ran, without having to infer it from the documents.
                "reranking_status": reranking_status,
                "chunk_ids": [doc.get("chunk_id") for doc in documents],
            },
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
        "retrieved_documents": documents,
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
            "output": {
                "documents": documents,
                "document_count": len(documents),
                "references": [doc.get("reference") for doc in documents],
                "provider": dependencies.web_provider.name,
                "simulated_count": sum(
                    1 for doc in documents if doc.get("simulated", True)
                ),
            },
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
    documents = state.get("retrieved_documents", [])

    ordered = [
        document
        for _, document in sorted(
            enumerate(documents), key=lambda item: _merge_key(item[1], item[0])
        )
    ]

    seen: set[str] = set()
    unique: list[RetrievedDocument] = []
    for document in ordered:
        reference = document.get("reference") or ""
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(document)

    blocks: list[str] = []
    included: list[RetrievedDocument] = []
    used = 0
    for document in unique:
        block = _context_block(document)
        if used + len(block) > MAX_CONTEXT_CHARACTERS:
            break
        blocks.append(block)
        included.append(document)
        used += len(block)

    # Citations are built from exactly the documents that made it into
    # the context, in the same order — so a citation always corresponds
    # to evidence the synthesis step can actually see. This is where
    # each document's provenance metadata is preserved rather than
    # collapsed into the context string.
    citations = [
        build_citation(document, position)
        for position, document in enumerate(included, start=1)
    ]

    context = "\n\n".join(blocks)
    summary = (
        f"Merged {len(blocks)} of {len(documents)} item(s) into "
        f"{len(context)} characters of context, carrying {len(citations)} citation(s)."
    )

    logger.info(
        "research_node_context_builder",
        run_id=state.get("run_id"),
        included=len(blocks),
        received=len(documents),
        citation_count=len(citations),
        context_characters=len(context),
    )

    return {
        "context": context,
        "citations": citations,
        "messages": [
            _message(
                role="aggregator",
                agent_name="context_builder",
                content=summary,
                metadata={"citations": citations},
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
                "citation_count": len(citations),
                "citations": citations,
            },
        },
    }


async def synthesis_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    """Produce the final, cited deliverable."""
    dependencies = _dependencies(config)
    objective = state.get("objective", state["query"])
    context = state.get("context", "")
    documents = state.get("retrieved_documents", [])
    # Citations come from the context builder, so synthesis cites
    # exactly the evidence that reached it — not the raw retrieval
    # output, which may have been de-duplicated or truncated to fit.
    incoming = state.get("citations", [])
    # Non-critical agents that failed earlier in the run. Synthesis
    # must state that the evidence is incomplete rather than present
    # partial results as if every source had been consulted.
    warnings = degraded_warnings(state)

    result = await dependencies.synthesizer.synthesize(
        query=state["query"],
        objective=objective,
        context=context,
        documents=documents,
        citations=incoming,
        warnings=warnings,
    )
    answer = result.answer
    citations = result.citations
    # The prompt a model-backed synthesizer actually sent, when there
    # was one; otherwise the rendered prompt this run would have used.
    # Recording the real thing is what makes the model call auditable.
    prompt = result.prompt or render_synthesis_prompt(
        objective=objective, query=state["query"], context=context
    )
    grounded_count = sum(1 for item in citations if not item["simulated"])
    simulated_count = len(citations) - grounded_count
    summary = (
        f"Synthesized the deliverable from {len(citations)} citation(s) "
        f"({grounded_count} grounded, {simulated_count} simulated); "
        f"grounding status '{result.grounding_status.value}'."
    )

    logger.info(
        "research_node_synthesis",
        run_id=state.get("run_id"),
        synthesizer=dependencies.synthesizer.name,
        citation_count=len(citations),
        grounded_citations=grounded_count,
        simulated_citations=simulated_count,
        degraded_warnings=len(warnings),
        answer_characters=len(answer),
        grounding_status=result.grounding_status.value,
        evidence_supplied=result.evidence_supplied,
        rejected_citations=len(result.rejected_citation_ids),
        # Model metadata, not model output: safe to log, and the proof
        # that the call went through the gateway.
        llm_model=result.model,
        llm_provider=result.provider,
        llm_latency_ms=result.latency_ms,
        # Sprint 9G: whether the configured provider answered, or a
        # fallback did after it failed.
        llm_fallback_used=result.fallback_used,
        llm_primary_model=result.primary_model,
        llm_primary_error_type=result.primary_error_type,
        llm_attempts=result.llm_attempts,
    )

    return {
        "final_answer": answer,
        "citations": citations,
        "grounding_status": result.grounding_status.value,
        # The graph's terminal node, so this is where the shared state
        # records the run reaching a successful end. The database row
        # remains authoritative; this mirrors it for any node or test
        # inspecting the final state directly.
        "status": ResearchRunStatus.COMPLETED.value,
        "messages": [
            _message(
                role="aggregator",
                agent_name=dependencies.synthesizer.name,
                content=answer,
                metadata={
                    "prompt": prompt,
                    "citations": citations,
                    "grounding_status": result.grounding_status.value,
                    "model": result.model,
                    "provider": result.provider,
                    "latency_ms": result.latency_ms,
                },
            )
        ],
        "step": {
            "node": ResearchNode.SYNTHESIS.value,
            "title": "Synthesize the deliverable",
            "summary": summary,
            "output": {
                "citations": citations,
                "citation_count": len(citations),
                "grounded_citations": grounded_count,
                "simulated_citations": simulated_count,
                "answer_characters": len(answer),
                "grounding_status": result.grounding_status.value,
                # How many evidence items the model was actually given.
                # With `rejected_citation_ids`, this is the auditable
                # record of the FINAL_CITATIONS ⊆ EVIDENCE_SENT
                # invariant: anything rejected is listed, not hidden.
                "evidence_supplied": result.evidence_supplied,
                "rejected_citation_ids": result.rejected_citation_ids,
                "model": result.model,
                "provider": result.provider,
                "latency_ms": result.latency_ms,
                # Sprint 9G. Additive: `model`/`provider` above keep
                # meaning "what answered", so nothing reading the
                # existing trace changes. These say how we got there —
                # a run that completed through a fallback must be
                # readable as such months later, not silently
                # attributed to the model that was configured.
                "fallback_used": result.fallback_used,
                "primary_model": result.primary_model,
                "primary_error_type": result.primary_error_type,
                "llm_attempts": result.llm_attempts,
            },
        },
    }


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------


def route_after_router(state: ResearchState) -> str:
    """Dispatch to the first selected retrieval agent, if any.

    Retrieval agents run in sequence rather than in parallel: they
    share one database session, and the stored step trace is persisted
    in execution order — sequencing keeps both deterministic. An agent
    the router did not select is never entered, so no unnecessary work
    is performed.
    """
    selected = state.get("selected_agents", [])
    if ResearchNode.ASSET_RETRIEVAL.value in selected:
        return ResearchNode.ASSET_RETRIEVAL.value
    if ResearchNode.WEB_RESEARCH.value in selected:
        return ResearchNode.WEB_RESEARCH.value
    return ResearchNode.CONTEXT_BUILDER.value


def route_after_asset_retrieval(state: ResearchState) -> str:
    """Continue to web research if it was selected, else merge context."""
    if ResearchNode.WEB_RESEARCH.value in state.get("selected_agents", []):
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


def _warning_section(warnings: list[str]) -> str:
    """Render degraded-mode notices, or nothing when the run was clean."""
    if not warnings:
        return ""
    body = "\n".join(f"- {warning}" for warning in warnings)
    return f"\n## Incomplete evidence\n{body}\n"


def _merge_key(document: RetrievedDocument, arrival: int) -> tuple[int, int, int]:
    """Ordering for the merged context: real evidence first, then by the
    retriever's own rank.

    Sorting purely by `score` — as this did before the retrieval
    pipeline became real — compares numbers from different retrievers
    that mean different things, which let a simulated web result
    outrank a genuine knowledge chunk whenever the mock's fixed score
    happened to be higher. Two rules fix that without inventing a
    common scale:

    1. Evidence from the project's own assets ranks above external
       evidence, matching the planner's stated preference.
    2. Within a source, the retriever's own final ordering (`rank`) is
       authoritative — so when the reranker reorders candidates, that
       order survives the merge rather than being undone by a re-sort
       on stage-1 similarity.

    `arrival` breaks ties for retrievers that supply no rank, keeping
    the merge deterministic.
    """
    priority = 0 if document.get("source") == ASSET_SOURCE else 1
    rank = document.get("rank")
    return (priority, rank if isinstance(rank, int) else arrival, arrival)


def document_score(document: RetrievedDocument) -> float:
    """Read a document's relevance score without assuming it is present.

    Ranking must not crash on a document produced by a retriever that
    omits the field; an unscored item simply sorts last.
    """
    try:
        return float(document.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _context_block(document: RetrievedDocument) -> str:
    """Render one evidence block for the merged context.

    Uses explicit lookups rather than `template.format(**document)`, so
    a document missing a field degrades to a placeholder instead of
    raising `KeyError` mid-run.
    """
    return CONTEXT_BLOCK_TEMPLATE.format(
        reference=document.get("reference") or "unknown",
        title=document.get("title") or "Untitled reference",
        source=document.get("source") or "unknown",
        score=document_score(document),
        snippet=document.get("snippet") or "",
    )


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
