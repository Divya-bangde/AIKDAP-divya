import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState } from "@/components/common/EmptyState";
import { SearchX } from "lucide-react";
import type { Citation } from "@/types/citation";

interface EvidencePanelProps {
  citations: Citation[];
}

/** Phase 21/24: the retrieval/rerank detail view, distinguishing
 * retrieval rank from rerank score explicitly — never merged into one
 * number, never called a probability. Reads the same `citations` data
 * `CitationList` does; this is a detail view of it, not a second data
 * source, per Phase 29 ("frontend only renders backend results"). */
export function EvidencePanel({ citations }: EvidencePanelProps) {
  if (citations.length === 0) {
    return (
      <EmptyState icon={SearchX} title="No relevant evidence was found." />
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Evidence</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {citations.map((citation, index) => (
          <div
            key={citation.chunk_id ?? citation.id ?? index}
            className="rounded-md border border-border p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium">
                {index + 1}. {citation.title ?? citation.file_name ?? "Untitled evidence"}
              </p>
              {citation.reranking_status && (
                <StatusBadge domain="reranking" value={citation.reranking_status} />
              )}
            </div>
            {citation.snippet && (
              <p className="mt-1 line-clamp-3 text-sm text-muted-foreground">
                {citation.snippet}
              </p>
            )}
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-4">
              {citation.retrieval_rank !== undefined && (
                <div>
                  <dt className="font-medium text-foreground">Retrieval rank</dt>
                  <dd>{citation.retrieval_rank}</dd>
                </div>
              )}
              {citation.retrieval_score !== undefined && (
                <div>
                  <dt className="font-medium text-foreground">Retrieval score</dt>
                  <dd>{citation.retrieval_score.toFixed(3)}</dd>
                </div>
              )}
              {citation.rerank_score !== undefined && (
                <div>
                  <dt className="font-medium text-foreground">Rerank score</dt>
                  <dd>{citation.rerank_score.toFixed(2)}</dd>
                </div>
              )}
              {citation.file_name && (
                <div>
                  <dt className="font-medium text-foreground">Source</dt>
                  <dd className="truncate">{citation.file_name}</dd>
                </div>
              )}
            </dl>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
