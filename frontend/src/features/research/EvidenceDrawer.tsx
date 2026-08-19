import * as DialogPrimitive from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, X } from "lucide-react";

import { StatusBadge } from "@/components/common/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { drawerVariants, overlayVariants } from "@/lib/motion";
import type { Citation } from "@/types/citation";

/** One evidence field. Renders nothing at all when the backend did not
 * supply the value, so the drawer never shows an invented or
 * placeholder measurement. */
function Detail({ label, value }: { label: string; value: string | number | undefined | null }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="min-w-0">
      <dt className="text-label uppercase text-muted-foreground">{label}</dt>
      <dd className="tabular mt-0.5 truncate font-mono text-xs text-foreground">{value}</dd>
    </div>
  );
}

/** The full record behind one citation, opened from the answer without
 * leaving the research page.
 *
 * Built on Radix Dialog so the panel is a real modal: focus is
 * trapped, Escape closes it, and it is announced as a dialog. Motion
 * only supplies the slide-in; `forceMount` hands mount control to
 * `AnimatePresence` so the exit animation can finish before Radix
 * unmounts the content.
 *
 * Every field below is optional and rendered only when present —
 * `retrieval_score` and `rerank_score` are kept visually and
 * semantically separate, and neither is ever converted to a percentage
 * or relabelled as confidence. */
export function EvidenceDrawer({
  citation,
  index,
  onClose,
}: {
  citation: Citation | null;
  index: number | null;
  onClose: () => void;
}) {
  const open = citation !== null;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <AnimatePresence>
        {open && citation && (
          <DialogPrimitive.Portal forceMount>
            <DialogPrimitive.Overlay asChild forceMount>
              <motion.div
                variants={overlayVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]"
              />
            </DialogPrimitive.Overlay>

            <DialogPrimitive.Content asChild forceMount>
              <motion.div
                variants={drawerVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-elevated shadow-float focus:outline-none"
              >
                <div className="flex items-start justify-between gap-4 border-b border-border p-5">
                  <div className="min-w-0">
                    <p className="text-label uppercase text-muted-foreground">
                      Evidence {index !== null ? `· ${index + 1}` : ""}
                    </p>
                    <DialogPrimitive.Title className="mt-1 text-section">
                      {citation.title ?? citation.file_name ?? "Untitled evidence"}
                    </DialogPrimitive.Title>
                    <DialogPrimitive.Description className="sr-only">
                      Retrieval and reranking detail for this citation.
                    </DialogPrimitive.Description>
                  </div>
                  <DialogPrimitive.Close className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <X className="h-4 w-4" />
                    <span className="sr-only">Close evidence panel</span>
                  </DialogPrimitive.Close>
                </div>

                <div className="flex-1 overflow-y-auto p-5">
                  <div className="mb-4 flex flex-wrap items-center gap-2">
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
                    {citation.reranking_status && (
                      <StatusBadge domain="reranking" value={citation.reranking_status} />
                    )}
                  </div>

                  {citation.simulated && (
                    <p className="mb-4 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs leading-relaxed text-foreground">
                      This is a placeholder produced by the mock web provider because no live
                      external research provider is configured. It contains no facts and was not
                      used to ground the answer.
                    </p>
                  )}

                  {citation.snippet && (
                    <div className="mb-5">
                      <p className="text-label uppercase text-muted-foreground">Snippet</p>
                      <p className="mt-2 rounded-lg border border-border bg-sunken p-3 text-sm leading-relaxed text-foreground">
                        {citation.snippet}
                      </p>
                    </div>
                  )}

                  <dl className="grid grid-cols-2 gap-4">
                    <Detail label="Citation ID" value={citation.id} />
                    <Detail label="Provider" value={citation.provider} />
                    <Detail label="Rank" value={citation.rank} />
                    <Detail label="Retrieval rank" value={citation.retrieval_rank} />
                    <Detail
                      label="Retrieval score"
                      value={citation.retrieval_score?.toFixed(3)}
                    />
                    <Detail label="Rerank score" value={citation.rerank_score?.toFixed(2)} />
                    <Detail label="Relevance threshold" value={citation.relevance_threshold} />
                    <Detail label="File" value={citation.file_name} />
                  </dl>

                  {(citation.chunk_id || citation.asset_id || citation.reference) && (
                    <dl className="mt-5 grid grid-cols-1 gap-3 border-t border-border pt-4">
                      <Detail label="Chunk ID" value={citation.chunk_id} />
                      <Detail label="Asset ID" value={citation.asset_id} />
                      <Detail label="Reference" value={citation.reference} />
                    </dl>
                  )}
                </div>
              </motion.div>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        )}
      </AnimatePresence>
    </DialogPrimitive.Root>
  );
}
