"""Regression tests for citation propagation through the research graph.

Covers the path that failed in run 57456906-7670-49a1-ae76-e57c8185f5bb:
`web_research` produced 5 references, `context_builder` merged all 5,
and `synthesis` nevertheless emitted zero citations because the
synthesizer discarded every item whose source was simulated.

Each test asserts one hop of the chain, so a future regression points
at the hop that broke rather than only at the end result:

    provider -> state.documents -> context_builder -> synthesis
             -> research_runs.citations / research_steps.output_payload
"""

import uuid

import pytest

from app.agents.planner.graph import get_research_graph
from app.agents.planner.nodes import (
    ExtractiveSynthesizer,
    GraphDependencies,
    MockWebResearchProvider,
    build_citation,
    context_builder_node,
    synthesis_node,
)
from app.agents.planner.planner import get_planner
from app.agents.planner.state import PROVENANCE_KEYS, ResearchNode
from app.modules.research.enums import ResearchRunStatus
from app.modules.research.models import ResearchRun
from app.modules.research.repository import ResearchStepRepository
from app.modules.research.service import ResearchExecutionService

EXPECTED_REFERENCES = 5

#: The fields every citation must carry, whatever produced it.
CITATION_FIELDS = {
    "id",
    "reference",
    "title",
    "source",
    "provider",
    "snippet",
    "score",
    "simulated",
}


def assert_citation_shape(citation: dict) -> None:
    """Assert a citation carries the core fields and nothing invented.

    Sprint 9E added optional provenance (`chunk_id`, `asset_id`, the
    per-stage retrieval scores) that a retriever attaches only when it
    genuinely has it, so an exact key-set match is no longer the
    contract. The bound is still two-sided: every core field must be
    present, and any extra key must be a declared provenance field —
    an unrecognised key is still a failure.
    """
    keys = set(citation)
    assert CITATION_FIELDS <= keys, f"missing core fields: {CITATION_FIELDS - keys}"
    unexpected = keys - CITATION_FIELDS - set(PROVENANCE_KEYS)
    assert not unexpected, f"unexpected citation fields: {unexpected}"


def web_only_dependencies() -> GraphDependencies:
    """Dependencies for a web-only run: no database access required."""
    return GraphDependencies(
        planner=get_planner(),
        asset_retriever=_UnusedAssetRetriever(),
        web_provider=MockWebResearchProvider(),
        synthesizer=ExtractiveSynthesizer(),
    )


class _UnusedAssetRetriever:
    """Fails loudly if a web-only run ever reaches asset retrieval."""

    name = "unused"

    async def retrieve(self, *, owner_id, project_id, query, limit):
        raise AssertionError("asset_retrieval must not run when include_assets=False")


# ---------------------------------------------------------------------------
# TEST 1 — the provider's references survive into LangGraph state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_research_references_reach_graph_state(research_query):
    """5 mock references must arrive in state with citation metadata intact."""
    provider = MockWebResearchProvider()
    documents = await provider.search(query=research_query, limit=EXPECTED_REFERENCES)

    assert len(documents) == EXPECTED_REFERENCES

    for document in documents:
        assert document["reference"].startswith("mock://"), "reference must be present"
        assert document["title"]
        assert document["snippet"]
        assert document["source"] == "web"
        # The metadata whose absence caused the bug: provenance has to
        # travel with the document, not be re-derived downstream.
        assert document["provider"] == provider.name
        assert document["simulated"] is True


# ---------------------------------------------------------------------------
# TEST 2 — context_builder keeps all 5 references associated with the context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_builder_preserves_all_references(research_query):
    """All 5 documents must survive merging as structured citations."""
    documents = await MockWebResearchProvider().search(
        query=research_query, limit=EXPECTED_REFERENCES
    )
    state = {
        "run_id": str(uuid.uuid4()),
        "query": research_query,
        "retrieved_documents": documents,
    }

    update = await context_builder_node(state, {"configurable": {}})
    citations = update["citations"]

    assert len(citations) == EXPECTED_REFERENCES
    assert update["step"]["output"]["citation_count"] == EXPECTED_REFERENCES
    assert len(update["step"]["output"]["citations"]) == EXPECTED_REFERENCES

    references = {citation["reference"] for citation in citations}
    assert references == {document["reference"] for document in documents}

    for citation in citations:
        assert_citation_shape(citation)
        assert citation["provider"] == "mock_web_v1"
        assert citation["simulated"] is True
    # Inline keys must be unique and stable.
    assert [c["id"] for c in citations] == ["c1", "c2", "c3", "c4", "c5"]


@pytest.mark.asyncio
async def test_context_builder_tolerates_documents_without_metadata():
    """A document missing citation metadata must not crash the run."""
    state = {
        "run_id": str(uuid.uuid4()),
        "query": "anything",
        # Deliberately missing provider, simulated, score, and title.
        "retrieved_documents": [{"reference": "partial://doc/1", "snippet": "Some text."}],
    }

    update = await context_builder_node(state, {"configurable": {}})
    citation = update["citations"][0]

    assert citation["reference"] == "partial://doc/1"
    assert citation["title"] == "Untitled reference"
    assert citation["provider"] == "unknown"
    assert citation["score"] == 0.0
    # Unlabelled evidence is treated as unverified, never as trusted.
    assert citation["simulated"] is True


# ---------------------------------------------------------------------------
# TEST 3 — synthesis returns the citations it received
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesis_returns_all_received_citations(research_query):
    """Synthesis given 5 citations must return 5 citations."""
    documents = await MockWebResearchProvider().search(
        query=research_query, limit=EXPECTED_REFERENCES
    )
    citations = [build_citation(doc, i) for i, doc in enumerate(documents, start=1)]
    state = {
        "run_id": str(uuid.uuid4()),
        "query": research_query,
        "objective": "Assess the industry.",
        "context": "irrelevant to the assertion",
        "retrieved_documents": documents,
        "citations": citations,
    }
    config = {"configurable": {"dependencies": web_only_dependencies()}}

    update = await synthesis_node(state, config)

    assert len(update["citations"]) == EXPECTED_REFERENCES
    assert update["step"]["output"]["citation_count"] == EXPECTED_REFERENCES
    assert update["step"]["output"]["simulated_citations"] == EXPECTED_REFERENCES
    assert update["step"]["output"]["grounded_citations"] == 0
    assert update["final_answer"]

    # Structured data, not just strings pasted into the answer body.
    for citation in update["citations"]:
        assert isinstance(citation, dict)
        assert_citation_shape(citation)

    # The answer must disclose that the evidence is simulated rather
    # than presenting it as verified.
    assert "simulated" in update["final_answer"].lower()


@pytest.mark.asyncio
async def test_synthesis_returns_empty_list_when_no_evidence():
    """Zero real citations must yield an empty list, never a fabrication."""
    state = {
        "run_id": str(uuid.uuid4()),
        "query": "unanswerable",
        "objective": "Nothing to find.",
        "context": "",
        "retrieved_documents": [],
        "citations": [],
    }
    config = {"configurable": {"dependencies": web_only_dependencies()}}

    update = await synthesis_node(state, config)

    assert update["citations"] == []
    assert update["step"]["output"]["citation_count"] == 0
    assert "No evidence could be retrieved" in update["final_answer"]


@pytest.mark.asyncio
async def test_full_graph_preserves_citations_end_to_end(research_query):
    """The compiled graph, web-only, must finish with 5 citations."""
    graph = get_research_graph()
    final_state = await graph.ainvoke(
        {
            "run_id": str(uuid.uuid4()),
            "project_id": str(uuid.uuid4()),
            "owner_id": str(uuid.uuid4()),
            "query": research_query,
            "include_assets": False,
            "include_web": True,
            "max_results": EXPECTED_REFERENCES,
        },
        config={"configurable": {"dependencies": web_only_dependencies()}},
    )

    assert len(final_state["retrieved_documents"]) == EXPECTED_REFERENCES
    assert len(final_state["citations"]) == EXPECTED_REFERENCES
    assert final_state["final_answer"]


# ---------------------------------------------------------------------------
# TEST 4 & 5 — persistence: research_runs.citations and research_steps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_run_persists_citations_and_step_payloads(
    session, project, research_query, monkeypatch
):
    """A real executed run must store its citations and per-step counts."""
    from app.modules.research import service as service_module

    monkeypatch.setattr(
        service_module, "build_dependencies", lambda _session: web_only_dependencies()
    )

    run = ResearchRun(
        project_id=project.id,
        owner_id=project.owner_id,
        query=research_query,
        status=ResearchRunStatus.PENDING,
        include_assets=False,
        include_web=True,
        max_results=EXPECTED_REFERENCES,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    await ResearchExecutionService(session).execute(run.id)
    await session.refresh(run)

    # TEST 4 — research_runs.citations
    assert run.status is ResearchRunStatus.COMPLETED
    assert run.final_answer
    assert run.citations is not None
    assert len(run.citations) == EXPECTED_REFERENCES
    for citation in run.citations:
        assert_citation_shape(citation)
        assert citation["reference"].startswith("mock://")
        assert citation["simulated"] is True

    # TEST 5 — research_steps carries the citation information
    steps = {
        step.node_name: step
        for step in await ResearchStepRepository(session).list_by_run(run.id)
    }

    web_step = steps[ResearchNode.WEB_RESEARCH.value]
    assert web_step.output_payload["document_count"] == EXPECTED_REFERENCES
    assert len(web_step.output_payload["references"]) == EXPECTED_REFERENCES

    context_step = steps[ResearchNode.CONTEXT_BUILDER.value]
    assert context_step.output_payload["citation_count"] == EXPECTED_REFERENCES
    assert len(context_step.output_payload["citations"]) == EXPECTED_REFERENCES

    synthesis_step = steps[ResearchNode.SYNTHESIS.value]
    assert synthesis_step.output_payload["citation_count"] == EXPECTED_REFERENCES
    assert len(synthesis_step.output_payload["citations"]) == EXPECTED_REFERENCES

    # Asset retrieval was disabled, so it must be recorded as skipped —
    # unchanged behaviour, asserted so the fix cannot regress it.
    assert steps[ResearchNode.ASSET_RETRIEVAL.value].status.value == "skipped"
