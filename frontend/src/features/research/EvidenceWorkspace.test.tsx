import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EvidenceWorkspace } from "@/features/research/EvidenceWorkspace";
import type { Citation } from "@/types/citation";
import type { components } from "@/types/api";

type VerifiedClaim = components["schemas"]["VerifiedClaimRead"];

/** Real data: run 7eacd7e5-fbf5-4c1e-9443-7c11c9b3852c, aguilar_cti,
 * captured live against the Sprint 16 Phase 8.10 backend. A genuine
 * multi-chunk contradiction (the model's own 73.5% claim, cited against
 * two different pages of the same real paper, both scoping 73.5% to
 * strategy S4 rather than stating it as the aggregate) alongside a real
 * SUPPORTED and two real UNVERIFIABLE claims, and a real case of shared
 * evidence: `c5` backs both the "1,000" and "200 + 800" claims.
 */
const REAL_QUERY = "What was the overall pass rate across all 1,000 generated executive reports?";

const REAL_CLAIMS: VerifiedClaim[] = [
  {
    kind: "claim",
    claim_text:
      "The overall pass rate across all 1,000 generated executive reports was 73.5% according to AI instrument scoring.",
    claim_type: "numeric",
    claimed_value: "73.5%",
    scope: "aggregate",
    source_reference_ids: ["c1", "c4"],
    unresolved_citation_ids: [],
    attributed_to_primary: true,
    verdict: "contradicted",
    evidence_state: "contradicted",
    matched_evidence_ids: ["c1", "c4"],
    reason:
      "every cited occurrence of '73.5%' is scoped to a named component, none is stated as an aggregate/overall figure",
  },
  {
    kind: "claim",
    claim_text: "The total number of AI-generated executive reports was 1,000.",
    claim_type: "numeric",
    claimed_value: "1,000",
    scope: "aggregate",
    source_reference_ids: ["c5"],
    unresolved_citation_ids: [],
    attributed_to_primary: true,
    verdict: "supported",
    evidence_state: "verified",
    matched_evidence_ids: ["c5"],
    reason: "'1,000' found in cited evidence",
  },
  {
    kind: "claim",
    claim_text: "The 1,000 reports were composed of 200 baseline reports (S0) and 800 strategy reports (S1–S4).",
    claim_type: "numeric",
    claimed_value: "200 + 800",
    scope: "component",
    source_reference_ids: ["c5"],
    unresolved_citation_ids: [],
    attributed_to_primary: true,
    verdict: "unverifiable",
    evidence_state: "unknown",
    matched_evidence_ids: [],
    reason: "cited evidence never mentions '200 + 800'",
  },
];

const REAL_CITATIONS: Citation[] = [
  {
    id: "c1",
    title: "Evaluating LLMs as a Bridge Between Cyber Threats and Business Risk (page 29)",
    snippet:
      "S4: One-Shot + BLUF 200 3.55 3.35 3.70 4.07 3.60 / 73.5% Table D-1. Strategy-Level Performance Summary...",
    reference: "asset:c1854871-a178-4a48-ba8d-0632c29da6fe#chunk-85",
    simulated: false,
    chunk_id: "c8487cba-71bc-4fd2-92b0-689261e46f4c",
  },
  {
    id: "c4",
    title: "Evaluating LLMs as a Bridge Between Cyber Threats and Business Risk (page 20)",
    snippet: "Gemma3:27b ... produced passing-quality executive CTI reports at a 73.5% rate under the S4 prompt configuration...",
    reference: "asset:c1854871-a178-4a48-ba8d-0632c29da6fe#chunk-59",
    simulated: false,
    chunk_id: "4c65cb14-3ebc-44d6-beb7-ae5cdb9ea045",
  },
  {
    id: "c5",
    title: "Evaluating LLMs as a Bridge Between Cyber Threats and Business Risk (page 6)",
    snippet:
      "The study generates 1,000 AI reports in total: 200 baseline reports (S0) and 800 strategy reports (200 per strategy, S1-S4).",
    reference: "asset:c1854871-a178-4a48-ba8d-0632c29da6fe#chunk-16",
    simulated: false,
    chunk_id: "d27fee9d-f479-455d-a642-4c64f8b37218",
  },
];

describe("EvidenceWorkspace", () => {
  it("renders the tree from Question down to every claim, selecting the first claim by default", () => {
    render(
      <EvidenceWorkspace
        query={REAL_QUERY}
        claims={REAL_CLAIMS}
        citations={REAL_CITATIONS}
        onSelectCitation={vi.fn()}
      />,
    );

    expect(screen.getByText(REAL_QUERY)).toBeInTheDocument();
    const tree = screen.getByRole("navigation", { name: /claim and evidence tree/i });
    expect(within(tree).getByText(REAL_CLAIMS[0].claim_text)).toBeInTheDocument();
    expect(within(tree).getByText(REAL_CLAIMS[1].claim_text)).toBeInTheDocument();
    expect(within(tree).getByText(REAL_CLAIMS[2].claim_text)).toBeInTheDocument();

    // The first claim is focused by default and its evidence expanded.
    const detail = screen.getByText(REAL_CLAIMS[0].claim_text, { selector: "p" });
    expect(detail).toBeInTheDocument();
  });

  it("shows BOTH real conflicting chunks side by side for the contradicted claim, not just one", async () => {
    const user = userEvent.setup();
    render(
      <EvidenceWorkspace
        query={REAL_QUERY}
        claims={REAL_CLAIMS}
        citations={REAL_CITATIONS}
        onSelectCitation={vi.fn()}
      />,
    );

    // Already selected by default (first claim), but click explicitly
    // to exercise the same path a user would.
    const tree = screen.getByRole("navigation", { name: /claim and evidence tree/i });
    await user.click(within(tree).getByText(REAL_CLAIMS[0].claim_text));

    expect(screen.getByText(/conflicting evidence \(2\)/i)).toBeInTheDocument();
    // Both real pages appear, not a single "winner" -- each also
    // labels its own row in the tree, so at least one occurrence of
    // each is expected regardless.
    expect(
      screen.getAllByText("Evaluating LLMs as a Bridge Between Cyber Threats and Business Risk (page 29)")
        .length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Evaluating LLMs as a Bridge Between Cyber Threats and Business Risk (page 20)")
        .length,
    ).toBeGreaterThan(0);
  });

  it("marks evidence shared by more than one claim with a badge, never an edge", async () => {
    const user = userEvent.setup();
    render(
      <EvidenceWorkspace
        query={REAL_QUERY}
        claims={REAL_CLAIMS}
        citations={REAL_CITATIONS}
        onSelectCitation={vi.fn()}
      />,
    );

    // c5's badge lives under claim 3's evidence row -- selecting a
    // claim expands it (claim 1 is expanded by default).
    const tree = screen.getByRole("navigation", { name: /claim and evidence tree/i });
    await user.click(within(tree).getByText(REAL_CLAIMS[2].claim_text));

    // c5 backs both claim 2 and claim 3 in this real run -- claim 3's
    // occurrence must say so.
    expect(screen.getByText(/also cited by claim 2/i)).toBeInTheDocument();
  });

  it("selecting a claim in the tree updates the detail panel to that claim", async () => {
    const user = userEvent.setup();
    render(
      <EvidenceWorkspace
        query={REAL_QUERY}
        claims={REAL_CLAIMS}
        citations={REAL_CITATIONS}
        onSelectCitation={vi.fn()}
      />,
    );

    const tree = screen.getByRole("navigation", { name: /claim and evidence tree/i });
    await user.click(within(tree).getByText(REAL_CLAIMS[1].claim_text));

    // `StatusBadge` swaps its old value out and the new one in via
    // `AnimatePresence mode="wait"`, so the new label lands a tick
    // after the click -- `findBy` waits for it.
    expect(await screen.findByText("Verified")).toBeInTheDocument();
    expect(await screen.findByText("Supported")).toBeInTheDocument();
    // The "verified means supported, not true" disclosure appears only
    // for a supported verdict, exactly where a reader could misread it.
    expect(screen.getByText(/not an independent confirmation/i)).toBeInTheDocument();
  });

  it("clicking a resolved evidence node opens the existing EvidenceDrawer callback, not a custom drawer", async () => {
    const user = userEvent.setup();
    const onSelectCitation = vi.fn();
    render(
      <EvidenceWorkspace
        query={REAL_QUERY}
        claims={REAL_CLAIMS}
        citations={REAL_CITATIONS}
        onSelectCitation={onSelectCitation}
      />,
    );

    await user.click(screen.getByRole("button", { name: "c1" }));

    expect(onSelectCitation).toHaveBeenCalledWith(REAL_CITATIONS[0], 0);
  });

  it("shows evidence supplied to the model but absent from this run's citations as unavailable, not missing or verified", () => {
    const claimsWithGap: VerifiedClaim[] = [
      {
        ...REAL_CLAIMS[1],
        source_reference_ids: ["c9"],
        matched_evidence_ids: ["c9"],
      },
    ];

    render(
      <EvidenceWorkspace
        query={REAL_QUERY}
        claims={claimsWithGap}
        citations={REAL_CITATIONS}
        onSelectCitation={vi.fn()}
      />,
    );

    // Appears once in the tree chip and once in the detail panel's own
    // gap card -- both must say "unavailable", never "missing".
    expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText(/not returned by this run's record/i)).toBeInTheDocument();
  });

  it("renders nothing when the run has no claims at all", () => {
    const { container } = render(
      <EvidenceWorkspace query={REAL_QUERY} claims={[]} citations={REAL_CITATIONS} onSelectCitation={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
