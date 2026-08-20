import { describe, expect, it } from "vitest";

import {
  availableStatuses,
  displayStatus,
  filterRuns,
} from "@/features/research/research-history";
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
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as ResearchRunRead;
}

describe("displayStatus", () => {
  it("prefers grounding_status when the backend supplied one", () => {
    expect(displayStatus(run({ status: "completed", grounding_status: "grounded" }))).toBe(
      "grounded",
    );
  });

  it("falls back to run status when there is no grounding outcome yet", () => {
    expect(displayStatus(run({ status: "running", grounding_status: null }))).toBe("running");
  });
});

describe("availableStatuses", () => {
  it("lists only statuses actually present, never an empty chip", () => {
    const runs = [
      run({ status: "completed", grounding_status: "grounded" }),
      run({ status: "running", grounding_status: null }),
    ];
    expect(availableStatuses(runs)).toEqual(["running", "grounded"]);
  });

  it("returns nothing for an empty list", () => {
    expect(availableStatuses([])).toEqual([]);
  });
});

describe("filterRuns", () => {
  const runs = [
    run({ id: "r1", query: "What challenges does ABC Poultry face?", status: "completed", grounding_status: "grounded" }),
    run({ id: "r2", query: "What is the capital of Japan?", status: "completed", grounding_status: "insufficient_evidence" }),
    run({ id: "r3", query: "Summarise Q2 revenue.", status: "running", grounding_status: null }),
  ];

  it("returns every run when no filter is applied", () => {
    expect(filterRuns(runs, { status: null, search: "" })).toHaveLength(3);
  });

  it("filters by the displayed status", () => {
    const result = filterRuns(runs, { status: "grounded", search: "" });
    expect(result.map((r) => r.id)).toEqual(["r1"]);
  });

  it("filters by a case-insensitive substring of the question", () => {
    const result = filterRuns(runs, { status: null, search: "japan" });
    expect(result.map((r) => r.id)).toEqual(["r2"]);
  });

  it("combines a status and a search term", () => {
    const result = filterRuns(runs, { status: "completed", search: "" });
    expect(result).toHaveLength(0); // no run's *displayed* status is "completed" — both completed runs have a grounding outcome instead
  });

  it("returns nothing when the search matches no query", () => {
    expect(filterRuns(runs, { status: null, search: "nonexistent" })).toEqual([]);
  });
});
