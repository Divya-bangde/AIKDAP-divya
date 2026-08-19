import { AlertTriangle, FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Citation } from "@/types/citation";

/** Phase 23: shows exactly what the backend returned per citation —
 * title, source, provider, snippet, rank, retrieval_rank vs
 * rerank_score kept visually distinct, and `simulated` flagged
 * explicitly rather than hidden. Never rendered as a probability or
 * percentage — a rerank score is a relevance ranking signal, not a
 * confidence value. */
export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Sources</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {citations.map((citation, index) => (
          <div
            key={citation.id ?? index}
            className="flex flex-col gap-1.5 border-b border-border pb-4 last:border-0 last:pb-0"
          >
            <div className="flex flex-wrap items-center gap-2">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="text-sm font-medium">
                [{citation.id ?? index + 1}] {citation.title ?? citation.file_name ?? "Untitled source"}
              </span>
              {citation.simulated && (
                <Badge variant="warning" className="gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  Simulated evidence
                </Badge>
              )}
              {citation.source && (
                <Badge variant="outline" className="capitalize">
                  {citation.source}
                </Badge>
              )}
              {citation.provider && (
                <Badge variant="muted">{citation.provider}</Badge>
              )}
            </div>

            {citation.snippet && (
              <p className="pl-6 text-sm text-muted-foreground">{citation.snippet}</p>
            )}

            <div className="flex flex-wrap gap-x-4 gap-y-1 pl-6 text-xs text-muted-foreground">
              {citation.retrieval_rank !== undefined && (
                <span>Retrieval rank: {citation.retrieval_rank}</span>
              )}
              {citation.rerank_score !== undefined && (
                <span>Rerank score: {citation.rerank_score.toFixed(2)}</span>
              )}
              {citation.reference && <span className="truncate">{citation.reference}</span>}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
