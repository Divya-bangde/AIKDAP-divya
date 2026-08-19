import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResearchResult } from "@/features/research/ResearchResult";
import type { components } from "@/types/api";

type ResearchRunDetail = components["schemas"]["ResearchRunDetail"];

function makeRun(overrides: Partial<ResearchRunDetail>): ResearchRunDetail {
  return {
    id: "run-1",
    project_id: "project-1",
    owner_id: "owner-1",
    task_id: null,
    query: "What challenges does ABC Poultry face?",
    status: "completed",
    include_assets: true,
    include_web: false,
    max_results: 5,
    objective: null,
    plan: null,
    final_answer: null,
    citations: [],
    grounding_status: null,
    error_message: null,
    celery_task_id: null,
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    duration_ms: 1200,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    steps: [],
    ...overrides,
  };
}

describe("ResearchResult", () => {
  it("shows Insufficient Evidence, zero evidence, and no fabricated answer when the backend says so", () => {
    const run = makeRun({
      grounding_status: "insufficient_evidence",
      final_answer: null,
      citations: [],
    });

    render(<ResearchResult run={run} />);

    expect(screen.getByText("Insufficient Evidence")).toBeInTheDocument();
    expect(screen.getByText(/did not contain enough relevant evidence/i)).toBeInTheDocument();
    expect(screen.getByText("Evidence found: 0")).toBeInTheDocument();
    expect(screen.getByText("Providers used: None")).toBeInTheDocument();
    // Never renders a "Research Result" success card for this state.
    expect(screen.queryByText("Research Result")).not.toBeInTheDocument();
  });

  it("renders a grounded answer with the exact grounding badge and citations", () => {
    const run = makeRun({
      grounding_status: "grounded",
      final_answer: "ABC Poultry faces feed cost inflation and biosecurity risk.",
      citations: [
        {
          id: "c1",
          title: "ABC Poultry FY2026 Review",
          source: "asset",
          snippet: "Feed costs rose 18% year-over-year.",
          retrieval_rank: 1,
          rerank_score: 6.15,
          simulated: false,
        },
      ],
    });

    render(<ResearchResult run={run} />);

    expect(screen.getByText("Grounded")).toBeInTheDocument();
    expect(
      screen.getByText("ABC Poultry faces feed cost inflation and biosecurity risk."),
    ).toBeInTheDocument();
    // Appears in both CitationList and EvidencePanel — both are
    // legitimate views of the same backend data (Phase 21).
    expect(screen.getAllByText(/ABC Poultry FY2026 Review/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Rerank score: 6.15")).toBeInTheDocument();
    expect(screen.queryByText("Simulated evidence")).not.toBeInTheDocument();
  });

  it("renders the Partially Grounded badge distinctly from Grounded", () => {
    const run = makeRun({
      grounding_status: "partially_grounded",
      final_answer: "Some of this is supported.",
      citations: [{ id: "c1", title: "Doc", simulated: false }],
    });

    render(<ResearchResult run={run} />);

    expect(screen.getByText("Partially Grounded")).toBeInTheDocument();
    expect(screen.queryByText("Grounded")).not.toBeInTheDocument();
  });

  it("flags simulated evidence explicitly rather than hiding it", () => {
    const run = makeRun({
      grounding_status: "grounded",
      final_answer: "Answer using simulated web evidence.",
      citations: [
        {
          id: "c1",
          title: "Simulated external reference",
          source: "web",
          simulated: true,
        },
      ],
    });

    render(<ResearchResult run={run} />);

    expect(screen.getByText("Simulated evidence")).toBeInTheDocument();
  });

  it("never displays a rerank score as a percentage or probability", () => {
    const run = makeRun({
      grounding_status: "grounded",
      final_answer: "Answer.",
      citations: [{ id: "c1", title: "Doc", rerank_score: 6.15 }],
    });

    render(<ResearchResult run={run} />);

    expect(screen.getByText("Rerank score: 6.15")).toBeInTheDocument();
    expect(screen.queryByText(/6\.15%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });

  it("shows provider/model and fallback information only when the backend supplies it", () => {
    const run = makeRun({
      grounding_status: "grounded",
      final_answer: "Answer via fallback.",
      citations: [{ id: "c1", title: "Doc" }],
      steps: [
        {
          id: "step-1",
          run_id: "run-1",
          step_index: 5,
          node_name: "synthesis",
          title: "Synthesize the deliverable",
          status: "completed",
          summary: null,
          output_payload: { provider: "groq", model: "openai/gpt-oss-120b", fallback_used: true },
          error_message: null,
          started_at: null,
          completed_at: null,
          duration_ms: null,
          created_at: new Date().toISOString(),
        },
      ],
    });

    render(<ResearchResult run={run} />);

    expect(screen.getByText("groq")).toBeInTheDocument();
    expect(screen.getByText(/Fallback used:/)).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });
});
