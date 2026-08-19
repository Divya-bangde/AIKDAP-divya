import { FileText } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";
import { AiProfilePanel } from "@/features/assets/AiProfilePanel";
import { DocumentCard } from "@/features/assets/DocumentCard";
import { UploadDropzone } from "@/features/assets/UploadDropzone";
import { usePolling } from "@/hooks/usePolling";
import * as assetsService from "@/services/assets";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];

const TERMINAL_PROCESSING_STATUSES = new Set(["completed", "failed", "unsupported"]);
const TERMINAL_EMBEDDING_STATUSES = new Set(["completed", "failed", "not_applicable"]);

/** `processing_status` and `ai_profile` are genuinely decoupled state
 * machines, not one pipeline (see `AssetProcessingService.process_asset`'s
 * own docstring: "the deterministic pipeline already succeeded and
 * processing_status is final... only ai_profile / each chunk's own
 * embedding_status" changes after that). A naive
 * `processing_status`-only check stops polling the instant extraction
 * finishes, while Qwen/BGE-M3 are still running -- caught live during
 * Sprint 9K's real end-to-end run, where the AI panel was still
 * "pending" seconds after polling had already stopped.
 *
 * `ai_profile.status`/`embedding_status` only ever leave "pending" if
 * `processing_status` reached `completed` (a failed/unsupported asset
 * never gets that far, and "pending" there is permanent and correct —
 * not something to wait on). */
function isSettled(asset: AssetRead): boolean {
  if (!TERMINAL_PROCESSING_STATUSES.has(asset.processing_status)) return false;
  if (asset.processing_status !== "completed") return true;
  return (
    asset.ai_profile.status !== "pending" &&
    TERMINAL_EMBEDDING_STATUSES.has(asset.ai_profile.embedding_status)
  );
}

function allSettled(assets: AssetRead[]): boolean {
  return assets.every(isSettled);
}

export function DocumentsSection({ projectId }: { projectId: string }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Polls only while at least one asset is still mid-pipeline
  // (pending/queued/extracting/chunking/embedding) — Phase 38: "avoid
  // unnecessary API calls."
  const assetsQuery = usePolling({
    queryKey: ["assets", projectId],
    queryFn: () => assetsService.listAssets(projectId),
    isTerminal: allSettled,
  });

  const selectedAsset = assetsQuery.data?.find((asset) => asset.id === selectedId);

  return (
    <div className="flex flex-col gap-4">
      <UploadDropzone projectId={projectId} />

      {assetsQuery.isLoading && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      )}

      {assetsQuery.isError && <ErrorState error={assetsQuery.error} />}

      {assetsQuery.isSuccess && assetsQuery.data.length === 0 && (
        <EmptyState icon={FileText} title="No documents uploaded yet." />
      )}

      {assetsQuery.isSuccess && assetsQuery.data.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="flex flex-col gap-2">
            {assetsQuery.data.map((asset) => (
              <DocumentCard
                key={asset.id}
                asset={asset}
                isSelected={asset.id === selectedId}
                onSelect={() => setSelectedId(asset.id === selectedId ? null : asset.id)}
              />
            ))}
          </div>
          <div>
            {selectedAsset ? (
              <AiProfilePanel profile={selectedAsset.ai_profile} />
            ) : (
              <p className="p-4 text-sm text-muted-foreground">
                Select a document to view its AI-understanding results.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
