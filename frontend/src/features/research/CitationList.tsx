import { motion } from "motion/react";
import { AlertTriangle, ChevronRight, FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { Citation } from "@/types/citation";

/** Shows exactly what the backend returned per citation — title,
 * source, provider, snippet, rank, and `retrieval_rank` vs
 * `rerank_score` kept visually distinct, with `simulated` flagged
 * explicitly rather than hidden. A rerank score is never rendered as a
 * probability or percentage: it is a cross-encoder relevance signal,
 * not a confidence value.
 *
 * Each row opens the evidence drawer rather than navigating, so
 * inspecting a source never costs the reader their place in the
 * answer. */
export function CitationList({
  citations,
  onSelect,
}: {
  citations: Citation[];
  onSelect: (citation: Citation, index: number) => void;
}) {
  if (citations.length === 0) return null;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Sources</CardTitle>
        <span className="tabular text-label uppercase text-muted-foreground">
          {citations.length} cited
        </span>
      </CardHeader>
      <CardContent>
        <motion.ul
          initial="hidden"
          animate="visible"
          variants={staggerContainer}
          className="flex flex-col gap-1"
        >
          {citations.map((citation, index) => (
            <motion.li key={citation.id ?? index} variants={staggerItem}>
              <button
                type="button"
                onClick={() => onSelect(citation, index)}
                className="group flex w-full items-start gap-3 rounded-lg border border-transparent p-3 text-left transition-all duration-200 hover:border-border hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="tabular mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent font-mono text-[11px] font-semibold text-accent-foreground">
                  {citation.id ?? index + 1}
                </span>

                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="text-sm font-medium">
                      {citation.title ?? citation.file_name ?? "Untitled source"}
                    </span>
                    {citation.simulated && (
                      <Badge variant="warning" className="gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        Simulated evidence
                      </Badge>
                    )}
                    {citation.provider && <Badge variant="muted">{citation.provider}</Badge>}
                  </span>

                  {citation.snippet && (
                    <span className="mt-1.5 line-clamp-2 block text-xs leading-relaxed text-muted-foreground">
                      {citation.snippet}
                    </span>
                  )}

                  <span className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px] text-muted-foreground">
                    {citation.retrieval_rank !== undefined && (
                      <span>Retrieval rank: {citation.retrieval_rank}</span>
                    )}
                    {citation.rerank_score !== undefined && (
                      <span>Rerank score: {citation.rerank_score.toFixed(2)}</span>
                    )}
                  </span>
                </span>

                <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5" />
              </button>
            </motion.li>
          ))}
        </motion.ul>
      </CardContent>
    </Card>
  );
}
