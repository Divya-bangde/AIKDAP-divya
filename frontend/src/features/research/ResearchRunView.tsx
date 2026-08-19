import { Loader2, X } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ResearchProgress } from "@/features/research/ResearchProgress";
import { ResearchResult } from "@/features/research/ResearchResult";
import { usePolling } from "@/hooks/usePolling";
import * as researchService from "@/services/research";
import type { components } from "@/types/api";

type ResearchRunDetail = components["schemas"]["ResearchRunDetail"];

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

function isTerminal(run: ResearchRunDetail): boolean {
  return TERMINAL_RUN_STATUSES.has(run.status);
}

/** Phase 19: polls `GET /research/runs/{id}` until the backend reports
 * a terminal status, then stops. The UI never claims "completed"
 * ahead of the backend — every render reflects exactly `run.status`. */
export function ResearchRunView({ runId }: { runId: string }) {
  const runQuery = usePolling({
    queryKey: ["research", "run", runId],
    queryFn: () => researchService.getResearchRun(runId),
    isTerminal,
  });

  if (runQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading research run…
      </div>
    );
  }

  if (runQuery.isError) {
    return <ErrorState error={runQuery.error} title="Could not load this research run" />;
  }

  const run = runQuery.data;
  if (!run) return null;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-base">{run.query}</CardTitle>
            <StatusBadge domain="researchRun" value={run.status} />
          </div>
        </CardHeader>
        <CardContent>
          <ResearchProgress steps={run.steps ?? []} />
        </CardContent>
      </Card>

      {run.status === "failed" && (
        <div className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
          <X className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p className="text-sm text-destructive">
            {run.error_message ?? "This research run failed."}
          </p>
        </div>
      )}

      {run.status === "completed" && <ResearchResult run={run} />}
    </div>
  );
}
