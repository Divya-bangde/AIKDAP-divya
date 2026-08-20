import type { BadgeProps } from "@/components/ui/badge";

type Variant = NonNullable<BadgeProps["variant"]>;

/** Maps every backend status vocabulary this frontend renders to a
 * badge variant + human label. One place, so the same status string
 * always looks the same everywhere it appears — never re-derived or
 * reinterpreted per component (Phase 22's grounding rule applies to
 * every other status vocabulary too: the frontend renders, it never
 * judges). Falls back to a neutral "outline" badge with the raw value
 * for any status not in this map, rather than hiding it. */
function badge(variant: Variant, label?: string) {
  return (value: string): { variant: Variant; label: string } => ({
    variant,
    label: label ?? value.replace(/_/g, " "),
  });
}

const MAPS: Record<string, Record<string, (value: string) => { variant: Variant; label: string }>> = {
  assetProcessing: {
    pending: badge("muted"),
    queued: badge("secondary"),
    extracting: badge("secondary", "Extracting"),
    chunking: badge("secondary", "Chunking"),
    embedding: badge("secondary", "Embedding"),
    completed: badge("success"),
    failed: badge("destructive"),
    unsupported: badge("warning"),
  },
  aiProfile: {
    pending: badge("muted"),
    completed: badge("success"),
    failed: badge("destructive"),
    unavailable: badge("warning"),
  },
  embedding: {
    pending: badge("muted"),
    processing: badge("secondary"),
    completed: badge("success"),
    failed: badge("destructive"),
    not_applicable: badge("muted", "Not applicable"),
  },
  researchRun: {
    // Sprint 9K.9: a bare "Pending"/"Running" answers "what job state is
    // this" — the question every list surface actually needs answered
    // is simpler: is AIKDAP still working on it. Both read as "In
    // Progress" for that reason; the exact lifecycle state remains the
    // real, unrelabelled `status` value inspectable in Technical Details.
    pending: badge("muted", "In Progress"),
    running: badge("secondary", "In Progress"),
    completed: badge("success"),
    // "Failed" alone doesn't say what failed — the pipeline never
    // reached synthesis, so there is no answer and no grounding
    // question to ask. See `grounding.failed` below for the sibling
    // case (synthesis ran but produced nothing usable): both are
    // "AIKDAP could not complete this research" to a reader who isn't
    // tracing which enum fired, so both render identically.
    failed: badge("destructive", "Research Failed"),
    cancelled: badge("warning"),
  },
  researchStep: {
    pending: badge("muted"),
    running: badge("secondary"),
    completed: badge("success"),
    failed: badge("destructive"),
    skipped: badge("muted"),
  },
  reranking: {
    completed: badge("success"),
    unavailable: badge("warning"),
    skipped: badge("muted"),
  },
  grounding: {
    grounded: badge("success", "Grounded"),
    partially_grounded: badge("warning", "Partially Grounded"),
    insufficient_evidence: badge("muted", "Insufficient Evidence"),
    // Synthesis ran but produced nothing usable — the same user-facing
    // story as `researchRun.failed` above (no answer came out of this
    // run), so it gets the same words. The technical distinction
    // between "never reached synthesis" and "synthesis itself failed"
    // stays real and inspectable (raw `status`/`grounding_status`), it
    // just isn't a distinction a reader needs made twice in different
    // words for the same outcome.
    failed: badge("destructive", "Research Failed"),
  },
  health: {
    healthy: badge("success"),
    configured: badge("secondary", "Configured"),
    degraded: badge("warning"),
    unavailable: badge("destructive"),
    quota_exhausted: badge("destructive", "Quota Exhausted"),
    rate_limited: badge("warning", "Rate Limited"),
    not_configured: badge("muted", "Not Configured"),
    configuration_error: badge("destructive", "Configuration Error"),
    loading: badge("secondary", "Loading"),
    disabled: badge("muted"),
    unknown: badge("outline"),
  },
  overallHealth: {
    healthy: badge("success"),
    degraded: badge("warning"),
    unhealthy: badge("destructive"),
  },
};

export type StatusDomain = keyof typeof MAPS;

export function statusBadge(domain: StatusDomain, value: string) {
  const resolver = MAPS[domain][value];
  return resolver ? resolver(value) : { variant: "outline" as Variant, label: value };
}

/** Whether `value` is a status this domain actually recognises, as
 * opposed to `statusBadge`'s neutral fallback for an unknown one — used
 * where a caller needs to know the difference (e.g. resolving a raw
 * status string against more than one domain). */
export function hasStatus(domain: StatusDomain, value: string): boolean {
  return value in MAPS[domain];
}
