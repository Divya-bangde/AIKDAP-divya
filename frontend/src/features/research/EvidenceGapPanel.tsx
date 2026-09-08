import { useQuery } from "@tanstack/react-query";
import { FileSearch } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { UploadDropzone } from "@/features/assets/UploadDropzone";
import * as assetsService from "@/services/assets";
import { analyzeResearchDocument } from "@/services/research";
import type { components } from "@/types/api";

type ResearchGap = components["schemas"]["ResearchGap"];

/** Surfaces the real reason a run declined to answer, at the exact
 * moment a reader hits that wall (Sprint 16 Phase 8.11 Part C).
 *
 * `analysis.py`'s gap classification (`ResearchGap`,
 * `sufficiency`/`sufficiency_reason`) already existed and was already
 * correct -- Phase 8.2 proved it against a real paper -- but nothing
 * in the UI ever rendered it. This does not compute a new verdict: it
 * calls the same `/documents/{asset_id}/analyze` endpoint
 * `DocumentAnalysisPanel` already calls manually, automatically, using
 * the run's own query as the goal, and renders exactly what comes
 * back. No gap text is invented here -- an item with no
 * `missing_information` renders no gap list at all, and the
 * `EmptyState`/upload action is the honest fallback while the check is
 * still running or found nothing to name.
 *
 * Scoped to the project's first asset: every real project in this
 * deployment has exactly one source paper, and `analyze` is a
 * per-asset endpoint with no run-level equivalent to call instead.
 */
export function EvidenceGapPanel({ projectId, query }: { projectId: string; query: string }) {
  const assetsQuery = useQuery({
    queryKey: ["assets", projectId],
    queryFn: () => assetsService.listAssets(projectId),
  });
  const asset = assetsQuery.data?.[0];

  const analysisQuery = useQuery({
    queryKey: ["document-analysis", asset?.id, query],
    queryFn: () =>
      analyzeResearchDocument(asset!.id, projectId, {
        goal: { type: "answer_question", description: query },
      }),
    enabled: Boolean(asset),
    // A best-effort check on top of an already-declined answer -- if
    // it fails, the reader still has the upload action below; retrying
    // a second model call for a nice-to-have isn't worth the wait.
    retry: false,
  });

  if (assetsQuery.isLoading || analysisQuery.isLoading) {
    return <Skeleton className="h-32" />;
  }

  const gaps = analysisQuery.data?.missing_information ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>What's missing</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {analysisQuery.data && (
          <p className="text-sm leading-relaxed text-foreground">
            {analysisQuery.data.sufficiency_reason}
          </p>
        )}

        {gaps.length > 0 ? (
          <ul className="flex flex-col gap-2">
            {gaps.map((gap: ResearchGap, index: number) => (
              <li
                key={index}
                className="flex flex-col gap-1 rounded-lg border border-border bg-sunken p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge domain="gapClassification" value={gap.classification} />
                  <span className="text-sm font-medium text-foreground">{gap.gap_type}</span>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground">{gap.description}</p>
                <p className="text-xs italic text-muted-foreground">Why it's needed: {gap.why_needed}</p>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={FileSearch}
            title="No specific gap was identified for this question."
            description="Uploading more source material to this project may still help future questions."
          />
        )}

        <UploadDropzone projectId={projectId} />
      </CardContent>
    </Card>
  );
}
