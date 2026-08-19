import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResearchPipeline } from "@/features/research/ResearchPipeline";
import type { components } from "@/types/api";

type ResearchStepRead = components["schemas"]["ResearchStepRead"];

function makeStep(overrides: Partial<ResearchStepRead>): ResearchStepRead {
  return {
    id: crypto.randomUUID(),
    run_id: "run-1",
    step_index: 0,
    node_name: "planner",
    title: "Plan the research run",
    status: "pending",
    summary: null,
    output_payload: null,
    error_message: null,
    started_at: null,
    completed_at: null,
    duration_ms: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("ResearchPipeline", () => {
  it("renders each step's real backend status verbatim", () => {
    render(
      <ResearchPipeline
        steps={[
          makeStep({ step_index: 0, title: "Plan", status: "completed" }),
          makeStep({ step_index: 1, title: "Retrieve", status: "running" }),
          makeStep({ step_index: 2, title: "Web", status: "skipped" }),
          makeStep({ step_index: 3, title: "Synthesize", status: "pending" }),
        ]}
      />,
    );

    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    // A skipped node is never dressed up as completed.
    expect(screen.getByText("skipped")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("orders steps by the backend's step_index, not array order", () => {
    render(
      <ResearchPipeline
        steps={[
          makeStep({ step_index: 2, title: "Third stage" }),
          makeStep({ step_index: 0, title: "First stage" }),
          makeStep({ step_index: 1, title: "Second stage" }),
        ]}
      />,
    );

    const titles = screen.getAllByText(/stage$/).map((el) => el.textContent);
    expect(titles).toEqual(["First stage", "Second stage", "Third stage"]);
  });

  it("shows only metrics the backend actually supplied", () => {
    render(
      <ResearchPipeline
        steps={[
          makeStep({
            node_name: "asset_retrieval",
            title: "Search the knowledge base",
            status: "completed",
            output_payload: { document_count: 3, reranking_status: "completed" },
          }),
        ]}
      />,
    );

    expect(screen.getByText("Chunks retrieved")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("Reranking")).toBeInTheDocument();
    // Nothing invented for keys this payload never contained.
    expect(screen.queryByText("Evidence supplied")).not.toBeInTheDocument();
    expect(screen.queryByText("Latency")).not.toBeInTheDocument();
  });

  it("surfaces a failed step's real error message in an alert", () => {
    render(
      <ResearchPipeline
        steps={[
          makeStep({
            node_name: "synthesis",
            title: "Synthesize the deliverable",
            status: "failed",
            error_message: "LLMQuotaExhaustedError: gemini was not called.",
          }),
        ]}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "LLMQuotaExhaustedError: gemini was not called.",
    );
  });

  it("waits for the backend rather than inventing stages when no steps exist yet", () => {
    render(<ResearchPipeline steps={[]} />);

    expect(screen.getByText(/Waiting for the pipeline to start/)).toBeInTheDocument();
    expect(screen.queryByText("completed")).not.toBeInTheDocument();
  });
});
