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
