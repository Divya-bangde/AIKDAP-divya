import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { Search, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { StatusBadge } from "@/components/common/StatusBadge";
import { allSettled } from "@/features/assets/asset-state";
import {
  activeWork,
  isActiveRun,
  type ActiveWorkItem,
} from "@/features/command-center/active-work";
import { usePolling } from "@/hooks/usePolling";
import * as assetsService from "@/services/assets";
import * as projectsService from "@/services/projects";
import * as researchService from "@/services/research";

const POLL_INTERVAL_MS = 3000;

/** A running research run has its own page; a mid-pipeline document
 * does not, so it links to its project's Documents tab. */
function destinationFor(item: ActiveWorkItem): string {
  return item.kind === "research"
    ? `/research/${item.id}`
    : `/projects/${item.projectId}?tab=documents`;
}

/**
 * "What AIKDAP is doing right now", as a toast in the bottom-right
 * corner of every workspace page — present only while a research run
 * or a document is genuinely in flight, gone the moment nothing is.
 *
 * Shares query keys with the Command Center, so both read one cache.
 * Polling stops once nothing is active; starting new work invalidates
 * these keys, which brings it back.
 */
export function ActiveWorkToast() {
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: projectsService.listProjects });
  const runsQuery = usePolling({
    queryKey: ["research", "runs", "all"],
    queryFn: () => researchService.listResearchRuns(),
    isTerminal: (runs) => !runs.some(isActiveRun),
    intervalMs: POLL_INTERVAL_MS,
  });
  const assetsQuery = usePolling({
    queryKey: ["assets", "all"],
    queryFn: () => assetsService.listAssets(),
    isTerminal: allSettled,
    intervalMs: POLL_INTERVAL_MS,
  });
  // Dismissal applies to this exact set of work; anything new re-opens it.
  const [dismissedKey, setDismissedKey] = useState<string | null>(null);

  const items = activeWork(runsQuery.data ?? [], assetsQuery.data ?? [], projectsQuery.data ?? []);
  const key = items.map((item) => `${item.kind}-${item.id}`).join("|");
  const visible = items.length > 0 && key !== dismissedKey;

  return (
    <AnimatePresence>
      {visible && (
        <motion.aside
          key="active-work"
          role="status"
          aria-label="Active work"
          initial={{ opacity: 0, x: 48 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 48 }}
          transition={{ type: "spring", stiffness: 320, damping: 30 }}
          className="fixed bottom-4 right-4 z-40 w-[min(22rem,calc(100vw-2rem))] rounded-card bg-card/85 p-3 shadow-float backdrop-blur-md print:hidden"
        >
          <div className="mb-2 flex items-center justify-between gap-3 px-1">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ai opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-ai" />
              </span>
              <p className="text-sm font-semibold">Active work</p>
              <span className="tabular text-xs text-muted-foreground">
                {items.length} in progress
              </span>
            </div>
            <button
              type="button"
              onClick={() => setDismissedKey(key)}
              aria-label="Dismiss active work"
              className="press rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <ul className="flex flex-col gap-0.5">
            {items.slice(0, 4).map((item) => (
              <li key={`${item.kind}-${item.id}`}>
                <Link
                  to={destinationFor(item)}
                  className="flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-sunken"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-ai/30 bg-ai/[0.08] text-ai">
                    {item.kind === "research" ? (
                      <Search className="h-3.5 w-3.5" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{item.label}</span>
                    {item.projectName && (
                      <span className="block truncate text-xs text-muted-foreground">
                        {item.projectName}
                      </span>
                    )}
                  </span>
                  <StatusBadge domain={item.statusDomain} value={item.status} />
                </Link>
              </li>
            ))}
          </ul>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
