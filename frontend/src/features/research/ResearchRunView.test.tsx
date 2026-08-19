import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResearchRunView } from "@/features/research/ResearchRunView";
import * as researchService from "@/services/research";
import { renderWithProviders } from "@/test/render";
import type { components } from "@/types/api";

vi.mock("@/services/research");

type ResearchRunDetail = components["schemas"]["ResearchRunDetail"];

function makeRun(overrides: Partial<ResearchRunDetail>): ResearchRunDetail {
  return {
    id: "run-1",
    project_id: "project-1",
    owner_id: "owner-1",
    task_id: null,
    query: "What challenges does ABC Poultry face?",
    status: "running",
    include_assets: true,
    include_web: false,
    max_results: 5,
    objective: null,
    plan: null,
    final_answer: null,
    citations: null,
    grounding_status: null,
    error_message: null,
    celery_task_id: null,
    started_at: new Date().toISOString(),
    completed_at: null,
    duration_ms: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    steps: [],
    ...overrides,
  };
}

describe("ResearchRunView polling (Phase 19)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders real backend steps while running, then polls again", async () => {
    const getRun = vi.mocked(researchService.getResearchRun);
    getRun.mockResolvedValueOnce(
      makeRun({
        steps: [
          {
            id: "s1",
            run_id: "run-1",
            step_index: 0,
            node_name: "planner",
            title: "Plan the research run",
            status: "completed",
            summary: null,
            output_payload: null,
            error_message: null,
            started_at: null,
            completed_at: null,
            duration_ms: null,
            created_at: new Date().toISOString(),
          },
        ],
      }),
    );

    renderWithProviders(<ResearchRunView runId="run-1" />);

    expect(await screen.findByText("Plan the research run")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    await waitFor(() => expect(getRun).toHaveBeenCalledTimes(1));
  });

  it("stops polling and shows the grounded result once the backend reports completed", async () => {
    vi.mocked(researchService.getResearchRun).mockResolvedValue(
      makeRun({
        status: "completed",
        grounding_status: "grounded",
        final_answer: "ABC Poultry faces feed cost inflation.",
        citations: [{ id: "c1", title: "ABC Poultry FY2026" }],
      }),
    );

    renderWithProviders(<ResearchRunView runId="run-1" />);

    expect(await screen.findByText("ABC Poultry faces feed cost inflation.")).toBeInTheDocument();
    expect(screen.getByText("Grounded")).toBeInTheDocument();
  });

  it("shows the real backend failure message, not a generic error, when a run fails", async () => {
    vi.mocked(researchService.getResearchRun).mockResolvedValue(
      makeRun({
        status: "failed",
        error_message: "LLMServiceUnavailableError: all providers are temporarily unavailable.",
      }),
    );

    renderWithProviders(<ResearchRunView runId="run-1" />);

    expect(
      await screen.findByText(
        "LLMServiceUnavailableError: all providers are temporarily unavailable.",
      ),
    ).toBeInTheDocument();
    // A failed run must never render the success result card.
    expect(screen.queryByText("Research Result")).not.toBeInTheDocument();
  });
});
