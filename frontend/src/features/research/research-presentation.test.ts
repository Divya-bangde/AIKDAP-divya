import { describe, expect, it } from "vitest";

import {
  isGroundedAnswer,
  outcomeLabel,
  presentationFor,
  runOutcome,
} from "@/features/research/research-presentation";

/** The six real `node_name` values a run actually produces, confirmed
 * against `backend/app/agents/planner/nodes.py`. If this list ever
 * changes, this test is the tripwire that says a new stage type needs
 * a presentation entry too. */
const REAL_NODE_NAMES = [
  "planner",
  "router",
  "asset_retrieval",
  "web_research",
  "context_builder",
  "synthesis",
];

describe("presentationFor", () => {
  it.each(REAL_NODE_NAMES)("gives %s a non-empty, non-technical title and description", (node) => {
    const presentation = presentationFor(node);
    expect(presentation.title.length).toBeGreaterThan(0);
    expect(presentation.description.length).toBeGreaterThan(0);
    // None of the presentation copy leaks the backend's own vocabulary
    // — an executive reading it should never meet "agent", "node",
    // "LLM", "embedding" or the node's own snake_case name.
    const text = `${presentation.title} ${presentation.description}`.toLowerCase();
    expect(text).not.toMatch(/agent|node|llm|embedding|reranker|chunk/);
    expect(text).not.toContain(node);
  });

  it("falls back to the raw node name for a stage type it doesn't recognise, rather than inventing one", () => {
    const presentation = presentationFor("some_future_node");
    expect(presentation.title).toBe("some_future_node");
    expect(presentation.description).toBe("");
  });
});

/** Sprint 9K.9: the one place that decides which outcome a run's badge
 * shows — Dashboard, `ResearchHistoryList` and `ResearchRunView` all
 * call this instead of each recomputing `grounding_status ?? status`,
 * so a run genuinely cannot look different across the three surfaces. */
describe("runOutcome", () => {
  it("prefers the grounding outcome once the backend has decided one", () => {
    expect(runOutcome({ status: "completed", grounding_status: "grounded" })).toEqual({
      domain: "grounding",
      value: "grounded",
    });
    expect(
      runOutcome({ status: "completed", grounding_status: "partially_grounded" }),
    ).toEqual({ domain: "grounding", value: "partially_grounded" });
    expect(
      runOutcome({ status: "completed", grounding_status: "insufficient_evidence" }),
    ).toEqual({ domain: "grounding", value: "insufficient_evidence" });
  });

  it("falls back to the run's own status while there is no grounding outcome yet", () => {
    expect(runOutcome({ status: "pending", grounding_status: null })).toEqual({
      domain: "researchRun",
      value: "pending",
    });
    expect(runOutcome({ status: "running", grounding_status: null })).toEqual({
      domain: "researchRun",
      value: "running",
    });
  });

  it("falls back to the run's own failed status when the pipeline never reached synthesis", () => {
    expect(runOutcome({ status: "failed", grounding_status: null })).toEqual({
      domain: "researchRun",
      value: "failed",
    });
  });
});

describe("outcomeLabel", () => {
  it.each([
    ["grounded", "Grounded"],
    ["partially_grounded", "Partially Grounded"],
    ["insufficient_evidence", "Insufficient Evidence"],
    ["pending", "In Progress"],
    ["running", "In Progress"],
    // Not explicitly relabelled in `lib/status.ts` — falls through to
    // the raw value, capitalized visually by the badge's own CSS class
    // rather than by this string (the same convention every other
    // unlabelled status already relies on).
    ["cancelled", "cancelled"],
  ])("labels %s as %s", (value, label) => {
    expect(outcomeLabel(value)).toBe(label);
  });

  it("labels a failed outcome the same way regardless of which enum reported it", () => {
    // grounding_status "failed" (synthesis ran but produced nothing
    // usable) and researchRun "failed" (the pipeline never reached
    // synthesis) are two different backend states with the same
    // real-world meaning to a reader: no answer came out of this run.
    expect(outcomeLabel("failed")).toBe("Research Failed");
  });
});

/** Sprint 9K.10: the "Grounded Answers" KPI rule, shared by the Command
 * Center tile and the per-project count on a project card. */
describe("isGroundedAnswer", () => {
  it("counts a run the backend actually marked grounded", () => {
    expect(isGroundedAnswer({ grounding_status: "grounded" })).toBe(true);
  });

  it("never counts a run merely because it completed", () => {
    // The whole point of the KPI: a run that finished but could not
    // ground an answer is not a grounded answer.
    expect(isGroundedAnswer({ grounding_status: null })).toBe(false);
    expect(isGroundedAnswer({ grounding_status: "insufficient_evidence" })).toBe(false);
  });

  it("excludes partially grounded rather than inflating the headline number", () => {
    expect(isGroundedAnswer({ grounding_status: "partially_grounded" })).toBe(false);
  });

  it("never counts a failed run", () => {
    expect(isGroundedAnswer({ grounding_status: "failed" })).toBe(false);
  });

  it("agrees with runOutcome — a run this counts always badges as Grounded", () => {
    const run = { status: "completed", grounding_status: "grounded" };
    expect(isGroundedAnswer(run)).toBe(true);
    expect(outcomeLabel(runOutcome(run).value)).toBe("Grounded");
  });
});
