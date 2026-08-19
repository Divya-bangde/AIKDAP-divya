import { motion } from "motion/react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ResearchPipeline } from "@/features/research/ResearchPipeline";
import { ResearchResult } from "@/features/research/ResearchResult";
import { usePolling } from "@/hooks/usePolling";
import { fadeUp } from "@/lib/motion";
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
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin text-ai" />
        Loading research run…
      </div>
    );
  }

  if (runQuery.isError) {
    return <ErrorState error={runQuery.error} title="Could not load this research run" />;
  }

  const run = runQuery.data;
  if (!run) return null;

  const isRunning = !isTerminal(run);

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
                 * level-one heading when this was an `h2`. */}
                <h1 className="mt-1 text-title">{run.query}</h1>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {isRunning && <Loader2 className="h-3.5 w-3.5 animate-spin text-ai" />}
                <StatusBadge domain="researchRun" value={run.status} />
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
