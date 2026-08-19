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
    pending: badge("muted"),
    running: badge("secondary"),
    completed: badge("success"),
    failed: badge("destructive"),
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
    failed: badge("destructive", "Failed"),
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
