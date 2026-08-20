import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ResearchHistoryList } from "@/features/research/ResearchHistoryList";
import { renderWithProviders } from "@/test/render";
import type { components } from "@/types/api";

type ResearchRunRead = components["schemas"]["ResearchRunRead"];

function run(overrides: Partial<ResearchRunRead> = {}): ResearchRunRead {
  return {
    id: "r1",
    project_id: "p1",
    owner_id: "u1",
    task_id: null,
    query: "What challenges does ABC Poultry face?",
    status: "completed",
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
    started_at: null,
    completed_at: null,
    duration_ms: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  } as ResearchRunRead;
}

describe("ResearchHistoryList", () => {
  it("shows the honest empty state when the project has no research yet", () => {
    renderWithProviders(<ResearchHistoryList runs={[]} />);

    expect(screen.getByText("No research runs yet.")).toBeInTheDocument();
  });

  it("filters by status without touching the network", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ResearchHistoryList
        runs={[
          run({ id: "r1", query: "Grounded question", grounding_status: "grounded" }),
          run({ id: "r2", query: "Unanswerable question", grounding_status: "insufficient_evidence" }),
        ]}
      />,
    );

    expect(screen.getByText("Grounded question")).toBeInTheDocument();
    expect(screen.getByText("Unanswerable question")).toBeInTheDocument();

    // Sprint 9K.9: filter chip labels now come from the same
    // `outcomeLabel` the status badges use, rather than a raw
    // underscore-replaced status string, so this matches the badge's
    // own "Grounded" text rather than the backend's lowercase enum.
    await user.click(screen.getByRole("button", { name: "Grounded" }));

    expect(screen.getByText("Grounded question")).toBeInTheDocument();
    expect(screen.queryByText("Unanswerable question")).not.toBeInTheDocument();
  });

  it("filters by a search term over the question text", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ResearchHistoryList
        runs={[
          run({ id: "r1", query: "What is driving feed cost inflation?" }),
          run({ id: "r2", query: "Summarise Q2 revenue." }),
          run({ id: "r3", query: "Third question" }),
          run({ id: "r4", query: "Fourth question" }),
        ]}
      />,
    );

    await user.type(
      screen.getByRole("searchbox", { name: /search research history/i }),
      "feed cost",
    );

    expect(screen.getByText("What is driving feed cost inflation?")).toBeInTheDocument();
    expect(screen.queryByText("Summarise Q2 revenue.")).not.toBeInTheDocument();
  });

  it("offers a way back when a filter matches nothing", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ResearchHistoryList
        runs={[
          run({ id: "r1", query: "Real question" }),
          run({ id: "r2", query: "Second question" }),
          run({ id: "r3", query: "Third question" }),
          run({ id: "r4", query: "Fourth question" }),
        ]}
      />,
    );

    await user.type(
      screen.getByRole("searchbox", { name: /search research history/i }),
      "nothing matches this",
    );

    expect(screen.getByText("No research matches this filter.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /clear filters/i }));

    expect(screen.getByText("Real question")).toBeInTheDocument();
  });

  it("does not show the filter bar for a small, unfiltered history", () => {
    renderWithProviders(<ResearchHistoryList runs={[run()]} />);

    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });

  it("shows a real citation count when the run has one, using the same field the run detail page counts", () => {
    renderWithProviders(
      <ResearchHistoryList
        runs={[run({ grounding_status: "grounded", citations: [{ id: "c1" }, { id: "c2" }] })]}
      />,
    );

    expect(screen.getByText(/2 citations/)).toBeInTheDocument();
  });

  it("never shows a citation count for a run with none, rather than claiming 0", () => {
    renderWithProviders(
      <ResearchHistoryList runs={[run({ grounding_status: "grounded", citations: [] })]} />,
    );

    expect(screen.queryByText(/citation/)).not.toBeInTheDocument();
  });

  it("shows the run's actual grounding outcome, not the bare fact the job finished (Sprint 9K.9)", () => {
    renderWithProviders(
      <ResearchHistoryList
        runs={[run({ status: "completed", grounding_status: "insufficient_evidence" })]}
      />,
    );

    expect(screen.getByText("Insufficient Evidence")).toBeInTheDocument();
    expect(screen.queryByText("Completed")).not.toBeInTheDocument();
  });

  it("shows an in-progress run consistently rather than the raw backend value", () => {
    renderWithProviders(<ResearchHistoryList runs={[run({ status: "running", grounding_status: null })]} />);

    expect(screen.getByText("In Progress")).toBeInTheDocument();
  });
});
