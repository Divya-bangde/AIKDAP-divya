import { motion } from "motion/react";
import { AlertTriangle, EyeOff, FileText, Hash, Layers, Link2, Puzzle } from "lucide-react";

import { StatusBadge } from "@/components/common/StatusBadge";
import { TechnicalDetails } from "@/components/common/TechnicalDetails";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { staggerContainer, staggerItem } from "@/lib/motion";
import { cn } from "@/lib/utils";
import type { Citation } from "@/types/citation";
import type { components } from "@/types/api";

type VerifiedClaim = components["schemas"]["VerifiedClaimRead"];

/** Card-level tint by verdict (Sprint 16 Phase 8.8) — a full border +
 * subtle background wash, the same treatment `ResearchResult` already
 * uses for its insufficient-evidence outcome card, not a new pattern.
 * Contradiction gets a visibly different card, not just a differently
 * colored badge inside an identical box: a reader scanning the list
 * must be able to spot the one contradicted claim without reading
 * every badge. Supported claims stay neutral — they are the expected
 * outcome, not something to highlight. */
function cardTintFor(verdict: VerifiedClaim["verdict"]): string {
  switch (verdict) {
    case "contradicted":
      return "border-destructive/30 bg-destructive/5";
    case "insufficient_evidence":
    case "unverifiable":
      return "border-warning/30 bg-warning/5";
    default:
      return "border-border";
  }
}

/** One evidence reference chip, in one of three states that must never
 * be visually confusable (Sprint 16 Phase 8.8 Part B):
 *
 * - `resolved` — a real citation the panel can open.
 * - `unavailable` — the id was validated against the evidence actually
 *   supplied to the model, but the API did not return that citation
 *   object (only possible for runs recorded before Phase 8.8's backend
 *   fix, which now unions this evidence into `citations`). This must
 *   read as "exists, temporarily not retrievable", never as broken or
 *   invented — no strikethrough, no destructive color.
 * - `not_supplied` — the model cited an id for this claim that was
 *   never part of the evidence it was given at all. This is the one
 *   genuinely adversarial case and is the only one styled destructive.
 */
function EvidenceChip({
  id,
  state,
  onOpen,
}: {
  id: string;
  state: "resolved" | "unavailable" | "not_supplied";
  onOpen?: () => void;
}) {
  if (state === "resolved") {
    return (
      <button
        type="button"
        onClick={onOpen}
        title={`Open evidence ${id}`}
        className="tabular flex h-6 min-w-6 items-center justify-center rounded-md bg-accent px-1.5 font-mono text-[11px] font-semibold text-accent-foreground transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {id}
      </button>
    );
  }

  if (state === "unavailable") {
    return (
      <span
        title={`${id} was supplied to the model as evidence for this claim, but its content is not available from this run's record`}
        className="tabular flex items-center gap-1 rounded-md border border-dashed border-muted-foreground/40 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
      >
        <EyeOff className="h-3 w-3 shrink-0" aria-hidden="true" />
        {id}
        <span className="font-sans font-normal not-italic">unavailable</span>
      </span>
    );
  }

  return (
    <span
      title={`${id} was cited by the model for this claim, but was never supplied as evidence for this run`}
      className="tabular flex items-center gap-1 rounded-md border border-dashed border-destructive/40 px-1.5 py-0.5 font-mono text-[11px] text-destructive line-through decoration-destructive/60"
    >
      <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
      {id}
    </span>
  );
}

/** Renders exactly what Phase 8.5's deterministic verifier decided about
 * each claim the model made (Sprint 16 Phase 8.7, refined 8.8) — never a
 * second opinion computed here, and never upgraded on the strength of
 * the model's own confidence.
 *
 * Three distinctions this layout exists to keep unmistakable:
 *
 * 1. `verdict` vs `evidence_state` — two badges, not one, because they
 *    answer different questions: `verdict` is the raw check against
 *    the cited text, `evidence_state` is the broader trust
 *    classification (Phase 8.1) that verdict feeds into.
 * 2. The claim's primary/supporting ROLE vs `evidence_state`'s own
 *    `supporting` value — EvidenceState.SUPPORTING is a different
 *    concept from "this claim is attributed to a supporting paper",
 *    so the role indicator sits in its own header slot, in a plain
 *    muted style, never among the verdict/evidence-state badges.
 * 3. An evidence id that is merely unavailable vs one that was never
 *    supplied at all (`EvidenceChip` above) — schema-valid is not the
 *    same as supported, but "not returned by the API" is also not the
 *    same as "invented", and conflating them would make a real backend
 *    gap look like a hallucination.
 *
 * Evidence ids open the same `EvidenceDrawer` `CitationList` already
 * uses, resolved against the run's own `citations` — no duplicated
 * snippet data ships inside a claim. */
export function ClaimEvidencePanel({
  claims,
  citations,
  onSelectCitation,
}: {
  claims: VerifiedClaim[];
  citations: Citation[];
  onSelectCitation: (citation: Citation, index: number) => void;
}) {
  if (claims.length === 0) return null;

  const citationById = new Map(
    citations.map((citation, index) => [citation.id, { citation, index }]),
  );

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Claim Evidence Panel</CardTitle>
        <span className="tabular text-label uppercase text-muted-foreground">
          {claims.length} claim{claims.length === 1 ? "" : "s"} checked
        </span>
      </CardHeader>
      <CardContent>
        <motion.ul
          initial="hidden"
          animate="visible"
          variants={staggerContainer}
          className="flex flex-col gap-3"
        >
          {claims.map((claim, index) => {
            const sourceIds = claim.source_reference_ids ?? [];
            const unresolvedIds = claim.unresolved_citation_ids ?? [];

            return (
              <motion.li
                key={index}
                variants={staggerItem}
                className={cn("rounded-lg border p-3.5 transition-colors", cardTintFor(claim.verdict))}
              >
                <div className="flex items-start justify-between gap-3">
                  {/* The claim itself leads — it is what the reader came
                   * to check, and everything below is evidence about it. */}
                  <p className="text-sm font-medium leading-relaxed text-foreground">
                    {claim.claim_text}
                  </p>
                  {/* The role indicator lives in its own header slot, not
                   * among the verdict/evidence badges below, precisely so
                   * it never reads as a third state on the same axis. */}
                  <span
                    className="flex shrink-0 items-center gap-1 whitespace-nowrap text-[11px] font-medium text-muted-foreground"
                    title={
                      claim.attributed_to_primary
                        ? "Attributed to the primary source"
                        : "Attributed to a supporting source"
                    }
                  >
                    {claim.attributed_to_primary ? (
                      <FileText className="h-3 w-3" aria-hidden="true" />
                    ) : (
                      <Link2 className="h-3 w-3" aria-hidden="true" />
                    )}
                    {claim.attributed_to_primary ? "Primary" : "Supporting"}
                  </span>
                </div>

                {/* The verification result: the two checks that matter
                 * most, given the most visual weight in the card. */}
                <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                  <StatusBadge domain="claimVerdict" value={claim.verdict} />
                  <StatusBadge domain="evidenceState" value={claim.evidence_state} />
                </div>

                {/* Claim metadata: what kind of figure this is, secondary
                 * to the verification result above it. */}
                {(claim.claimed_value || claim.scope) && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {claim.claim_type === "numeric" && claim.claimed_value && (
                      <Badge variant="muted" className="tabular gap-1 font-mono">
                        <Hash className="h-3 w-3" />
                        {claim.claimed_value}
                      </Badge>
                    )}
                    {claim.scope && (
                      <Badge variant="outline" className="gap-1 capitalize">
                        {claim.scope === "aggregate" ? (
                          <Layers className="h-3 w-3" />
                        ) : (
                          <Puzzle className="h-3 w-3" />
                        )}
                        {claim.scope}
                      </Badge>
                    )}
                  </div>
                )}

                {(sourceIds.length > 0 || unresolvedIds.length > 0) && (
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                    <span className="text-label uppercase text-muted-foreground">Evidence</span>
                    {sourceIds.map((id) => {
                      const match = citationById.get(id);
                      return (
                        <EvidenceChip
                          key={id}
                          id={id}
                          state={match ? "resolved" : "unavailable"}
                          onOpen={match ? () => onSelectCitation(match.citation, match.index) : undefined}
                        />
                      );
                    })}
                    {unresolvedIds.map((id) => (
                      <EvidenceChip key={id} id={id} state="not_supplied" />
                    ))}
                  </div>
                )}

                {claim.reason && (
                  <TechnicalDetails id={`claim-${index}`} className="mt-2.5">
                    <p className="text-xs leading-relaxed text-muted-foreground">{claim.reason}</p>
                  </TechnicalDetails>
                )}
              </motion.li>
            );
          })}
        </motion.ul>
      </CardContent>
    </Card>
  );
}
