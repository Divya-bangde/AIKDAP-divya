import { FileText, Search, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { StatusBadge } from "@/components/common/StatusBadge";
import { Stagger, StaggerItem } from "@/components/motion/PageTransition";
import { Card, CardContent } from "@/components/ui/card";
import type { ActiveWorkItem } from "@/features/command-center/active-work";
import { formatRelativeTime } from "@/lib/format";

/** Where a row of active work should navigate: a running research run
 * has somewhere to watch it complete, but a mid-pipeline document does
 * not have its own route — the closest useful place is the project's
 * Documents tab, where `AiProfilePanel` shows exactly this state. */
function destinationFor(item: ActiveWorkItem): string {
  return item.kind === "research"
    ? `/research/${item.id}`
    : `/projects/${item.projectId}?tab=documents`;
}

/**
 * "What AIKDAP is doing right now" — the one thing the previous
 * dashboard never distinguished from "what it did recently".
 *
 * Every row is real, in-flight backend state: a research run still
 * `pending`/`running`, or a document that has not yet settled through
 * extraction, understanding and embedding (Sprint 9K.5). Nothing here
 * is a live progress bar or a fabricated percentage — the same
 * discipline `ResearchPipeline` already holds to. When nothing is
 * active the panel says so plainly rather than disappearing, so its
 * absence is never confused with "not loaded yet".
 */
export function ActiveWorkPanel({
  items,
  isLoading,
}: {
  items: ActiveWorkItem[];
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              {items.length > 0 && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ai opacity-60" />
              )}
              <span
                className={
                  items.length > 0
                    ? "relative inline-flex h-2 w-2 rounded-full bg-ai"
                    : "relative inline-flex h-2 w-2 rounded-full bg-muted-foreground/40"
                }
              />
            </span>
            <h2 className="text-section">Active Work</h2>
          </div>
          {items.length > 0 && (
            <span className="tabular text-label uppercase text-muted-foreground">
              {items.length} in progress
            </span>
          )}
        </div>

        {isLoading ? (
          <div className="flex flex-col gap-2">
            <div className="h-12 animate-pulse rounded-lg bg-sunken" />
            <div className="h-12 animate-pulse rounded-lg bg-sunken" />
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing running right now. Start a research question or upload a document to see it
            here while AIKDAP works.
          </p>
        ) : (
          <Stagger className="flex flex-col gap-1">
            {items.slice(0, 6).map((item) => (
              <StaggerItem key={`${item.kind}-${item.id}`}>
                <Link
                  to={destinationFor(item)}
                  className="group flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-sunken"
                >
                  {/* A plain span, not a looping Motion animation: an
                   * infinite opacity pulse here would be exactly the
                   * "constant floating" this sprint's motion rules
                   * warn against, and — because `MotionConfig
                   * reducedMotion="user"` deliberately spares opacity
                   * (see `lib/motion.ts`) — a perpetual `animate` prop
                   * would keep looping even under
                   * `prefers-reduced-motion`, unlike every other
                   * decorative loop in this product. The row's status
                   * badge and the section's own "N in progress" count
                   * already say this is active; the icon doesn't also
                   * need to move. */}
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-ai/30 bg-ai/[0.08] text-ai">
                    {item.kind === "research" ? (
                      <Search className="h-3.5 w-3.5" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                  </span>

                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">{item.label}</span>
                      {item.kind === "document" && (
                        <FileText
                          aria-hidden="true"
                          className="h-3 w-3 shrink-0 text-muted-foreground"
                        />
                      )}
                    </span>
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                      {item.projectName && <span className="truncate">{item.projectName}</span>}
                      <span aria-hidden="true">·</span>
                      <span>{formatRelativeTime(item.updatedAt)}</span>
                    </span>
                  </span>

                  <StatusBadge domain={item.statusDomain} value={item.status} />
                </Link>
              </StaggerItem>
            ))}
          </Stagger>
        )}
      </CardContent>
    </Card>
  );
}
