import { motion } from "motion/react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { ResearchRunSkeleton } from "@/components/common/Skeletons";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ResearchPipeline } from "@/features/research/ResearchPipeline";
import { researchLayoutId } from "@/features/research/ResearchHistoryList";
import { ResearchResult } from "@/features/research/ResearchResult";
import { runOutcome } from "@/features/research/research-presentation";
import { usePolling } from "@/hooks/usePolling";
import { fadeUp, layoutSpring } from "@/lib/motion";
import * as researchService from "@/services/research";
import type { components } from "@/types/api";

type ResearchRunDetail = components["schemas"]["ResearchRunDetail"];

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

function isTerminal(run: ResearchRunDetail): boolean {
  return TERMINAL_RUN_STATUSES.has(run.status);
}

/** Polls `GET /research/runs/{id}` until the backend reports a terminal
 * status, then stops. The UI never claims "completed" ahead of the
 * backend — every render reflects exactly `run.status`. */
export function ResearchRunView({ runId }: { runId: string }) {
  const runQuery = usePolling({
    queryKey: ["research", "run", runId],
    queryFn: () => researchService.getResearchRun(runId),
    isTerminal,
  });

  if (runQuery.isLoading) {
    return <ResearchRunSkeleton />;
  }

  if (runQuery.isError) {
    return <ErrorState error={runQuery.error} title="Could not load this research run" />;
  }

  const run = runQuery.data;
  if (!run) return null;

  const isRunning = !isTerminal(run);
  const outcome = runOutcome(run);

  return (
    <div className="flex flex-col gap-6">
      <motion.div initial="hidden" animate="visible" variants={fadeUp}>
        <Card className="overflow-hidden">
          <CardHeader className="gap-3 border-b border-border bg-sunken/50">
            {/* role="status" (implicit aria-live="polite") announces only
             * when the badge's own text actually changes -- i.e. when the
             * backend reports a new run status -- not on every poll tick
             * that returns the same status, since aria-live fires on DOM
             * mutation, not on refetch. The per-step list below is
             * deliberately outside this region: announcing every step
             * transition would be noise a screen-reader user didn't ask
             * for. */}
            <div className="flex flex-wrap items-start justify-between gap-3" role="status">
              <div className="min-w-0">
                <p className="text-label uppercase text-muted-foreground">Research query</p>
                {/* The query is this page's subject, so it is the page's
                 * single `h1` — axe flagged the run view as having no
                 * level-one heading when this was an `h2`.
                 *
                 * It also carries the `layoutId` of the row that was
                 * clicked in the project's research history, so arriving
                 * here animates that question into the heading rather
                 * than swapping one page for another: the run reads as
                 * the history item expanded, which is what it is. */}
                <motion.h1
                  layoutId={researchLayoutId(run.id)}
                  transition={layoutSpring}
                  className="mt-1 text-title"
                >
                  {run.query}
                </motion.h1>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {isRunning && <Loader2 className="h-3.5 w-3.5 animate-spin text-ai" />}
                {/* Once the backend has decided an outcome, that outcome —
                 * not the bare fact that the async job finished — is what
                 * belongs in the page's most prominent badge.
                 *
                 * `run.status === "completed"` only means the pipeline
                 * ran to the end; it says nothing about whether an answer
                 * came out of it. Showing it alone put an identical green
                 * "Completed" pill here for a fully grounded answer AND
                 * for a deliberate insufficient-evidence decline — the
                 * one outcome this product exists to make unmistakable
                 * (confirmed side-by-side in a real browser, Sprint
                 * 9K.7). `runOutcome` (Sprint 9K.9) is the one place this
                 * resolution now lives — Dashboard and
                 * `ResearchHistoryList` render the same outcome for the
                 * same run through the same function. */}
                <StatusBadge domain={outcome.domain} value={outcome.value} />
              </div>
            </div>
          </CardHeader>

          <CardContent className="pt-6">
            <p className="mb-4 text-label uppercase text-muted-foreground">
              AI research pipeline
            </p>
            <ResearchPipeline steps={run.steps ?? []} />
          </CardContent>
        </Card>
      </motion.div>

      {run.status === "failed" && (
        <motion.div initial="hidden" animate="visible" variants={fadeUp}>
          {/* The failure experience: states plainly that the pipeline
           * could not complete, and shows the backend's own already
           * scrubbed message. `LLMError` runs `scrub_secrets` in its
           * constructor, so no credential can reach this text, and the
           * frontend adds no stack trace of its own. */}
          <Card role="alert" className="overflow-hidden border-destructive/30">
            <div className="h-1 w-full bg-destructive/60" />
            <CardContent className="flex items-start gap-3 p-5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-destructive/10 text-destructive">
                <AlertTriangle className="h-4.5 w-4.5" />
              </div>
              <div className="min-w-0">
                <p className="text-section">Research could not be completed</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  The intelligence pipeline could not finish synthesis. No answer was generated
                  and nothing was invented in its place.
                </p>
                {run.error_message && (
                  <p className="mt-3 rounded-lg border border-border bg-sunken p-3 font-mono text-xs leading-relaxed text-foreground">
                    {run.error_message}
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {run.status === "completed" && <ResearchResult run={run} />}
    </div>
  );
}
