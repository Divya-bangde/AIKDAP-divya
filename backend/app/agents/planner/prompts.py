"""Prompt templates for the research workflow.

No LLM is called in this sprint. These templates are still real and
still rendered: each node records the exact prompt it *would* send in
its `agent_messages.metadata`, which makes the mock run auditable and
means the switch to a real model is a change of executor, not a change
of contract (see `planner.PlannerStrategy` and `nodes.Synthesizer`).

Keep these as plain `str.format` templates rather than LangChain
`PromptTemplate` objects: the abstraction points that consume them are
provider-agnostic, and nothing here should depend on a specific LLM
client library until one is actually chosen.
"""

PLANNER_SYSTEM_PROMPT = """You are the Planner Agent for AIKDAP, an AI work operating system.
You do not answer the user's question yourself.
You decompose the request into an ordered execution plan for specialized agents.

Available executors:
- asset_retrieval: searches the project's own knowledge base (uploaded and generated assets).
- web_research: searches external public sources.
- context_builder: merges retrieved evidence into a single working context.
- synthesis: produces the final deliverable from that context.

Rules:
- Always finish with context_builder followed by synthesis.
- Only include a retrieval executor the user has enabled.
- Prefer the project's own knowledge base before external sources.
- State a single, concrete objective the run will be judged against."""

PLANNER_USER_TEMPLATE = """Request:
{query}

Enabled retrieval sources: {sources}
Maximum evidence items per source: {max_results}

Produce the execution plan."""

ROUTER_SYSTEM_PROMPT = """You are the Router for AIKDAP's research workflow.
Given an execution plan, determine which retrieval executors must run and in what order.
Do not invent executors that are not present in the plan."""

ROUTER_USER_TEMPLATE = """Objective:
{objective}

Planned steps:
{steps}

Determine the retrieval route."""

SYNTHESIS_SYSTEM_PROMPT = """You are the Synthesis Agent for AIKDAP.
You produce the final deliverable from retrieved evidence.

Rules:
- Ground every claim in the supplied evidence. Never introduce facts the evidence does not contain.
- Cite the reference key of each evidence item you use.
- If the evidence is insufficient, say so explicitly instead of speculating.
- Clearly mark any evidence flagged as simulated."""

SYNTHESIS_USER_TEMPLATE = """Objective:
{objective}

Original request:
{query}

Evidence:
{context}

Produce the final answer with citations."""

#: Rendered into the working context, one block per retrieved document.
CONTEXT_BLOCK_TEMPLATE = """[{reference}] {title} (source={source}, relevance={score})
{snippet}"""


# ---------------------------------------------------------------------------
# Grounded synthesis (Sprint 9E)
# ---------------------------------------------------------------------------
#
# The templates above describe the run for the audit trail. The ones
# below are sent verbatim to a real model through the LLM gateway, so
# they are written as instructions to that model rather than as a
# description of the workflow.

GROUNDED_SYNTHESIS_SYSTEM_PROMPT = """You are the AIKDAP research synthesis engine.

Answer the user's question using ONLY the supplied evidence.
The supplied evidence is the sole source of truth for this response.

Rules:
- Do not invent facts, numbers, entities, dates, or conclusions.
- Do not use outside knowledge to fill gaps, even if you are confident it is correct.
- Every factual claim must be traceable to one or more supplied evidence items.
- Cite evidence by its exact id (for example c1, c2) inline, immediately after the claim it supports.
- Only cite ids that appear in the supplied evidence. Never invent an id.
- If the evidence does not contain enough information to answer, say so plainly and do not answer anyway.
- Do not pad the answer with background the evidence does not contain.

Respond with a single JSON object and nothing else:

{
  "answer": "the answer in markdown, with inline [c1]-style citations",
  "citation_ids": ["the ids you actually relied on"],
  "grounding_status": "grounded" | "insufficient_evidence"
}

Use "insufficient_evidence" when the evidence cannot answer the question.
In that case, "answer" must explain what is missing and "citation_ids" must be empty."""

GROUNDED_SYNTHESIS_USER_TEMPLATE = """Question:
{query}

Objective:
{objective}

Evidence:
{evidence}

Answer the question using only the evidence above."""

#: One evidence item as the synthesis model sees it. The id here is the
#: citation id, and it is the only handle the model is given — so a
#: returned id can always be checked against what was supplied.
GROUNDED_EVIDENCE_BLOCK_TEMPLATE = """[{id}] {title} (source={source})
{snippet}"""


def render_grounded_evidence(citations: list[dict]) -> str:
    """Render the evidence block list exactly as the model will see it.

    Reads each field defensively for the same reason `_context_block`
    does: a citation assembled from a partially-populated document must
    degrade to a placeholder rather than raise mid-run.
    """
    if not citations:
        return "(no evidence retrieved)"
    return "\n\n".join(
        GROUNDED_EVIDENCE_BLOCK_TEMPLATE.format(
            id=citation.get("id") or "unknown",
            title=citation.get("title") or "Untitled reference",
            source=citation.get("source") or "unknown",
            snippet=citation.get("snippet") or "",
        )
        for citation in citations
    )


def render_grounded_synthesis_prompt(
    *, objective: str, query: str, evidence: str
) -> str:
    """Render the user half of the grounded synthesis request.

    The system half is `GROUNDED_SYNTHESIS_SYSTEM_PROMPT`; they are kept
    separate because the gateway sends them as distinct messages.
    """
    return GROUNDED_SYNTHESIS_USER_TEMPLATE.format(
        objective=objective, query=query, evidence=evidence
    )


def render_planner_prompt(*, query: str, sources: list[str], max_results: int) -> str:
    """Render the full planner prompt exactly as it would be sent."""
    return "\n\n".join(
        (
            PLANNER_SYSTEM_PROMPT,
            PLANNER_USER_TEMPLATE.format(
                query=query,
                sources=", ".join(sources) if sources else "none",
                max_results=max_results,
            ),
        )
    )


def render_router_prompt(*, objective: str, steps: list[str]) -> str:
    """Render the full router prompt exactly as it would be sent."""
    return "\n\n".join(
        (
            ROUTER_SYSTEM_PROMPT,
            ROUTER_USER_TEMPLATE.format(
                objective=objective,
                steps="\n".join(f"- {step}" for step in steps) if steps else "- (none)",
            ),
        )
    )


def render_synthesis_prompt(*, objective: str, query: str, context: str) -> str:
    """Render the full synthesis prompt exactly as it would be sent."""
    return "\n\n".join(
        (
            SYNTHESIS_SYSTEM_PROMPT,
            SYNTHESIS_USER_TEMPLATE.format(
                objective=objective,
                query=query,
                context=context or "(no evidence retrieved)",
            ),
        )
    )
