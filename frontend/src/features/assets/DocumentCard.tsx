import { motion } from "motion/react";
import { FileText } from "lucide-react";

import { StatusBadge } from "@/components/common/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import { isSettled } from "@/features/assets/asset-state";
import { cn } from "@/lib/utils";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];

interface DocumentCardProps {
  asset: AssetRead;
  isSelected: boolean;
  onSelect: () => void;
}

export function DocumentCard({ asset, isSelected, onSelect }: DocumentCardProps) {
  // "Still working" is the exact inverse of the settle check the
  // polling loop uses, so the indicator and the polling can never
  // disagree about whether this document is finished.
  const working = !isSettled(asset);

  return (
    <motion.div whileHover={{ x: 2 }} transition={{ duration: 0.15 }}>
      <Card
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect();
          }
        }}
        aria-pressed={isSelected}
        className={cn(
          "cursor-pointer transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          isSelected
            ? "border-primary/60 bg-accent/30 shadow-raised"
            : "hover:border-border-strong hover:shadow-raised",
        )}
      >
        <CardContent className="flex items-start gap-3 p-4">
          <div
            className={cn(
              "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
              working ? "bg-ai-soft text-ai" : "bg-secondary text-muted-foreground",
              working && "ai-pulse-ring",
            )}
          >
            <FileText className="h-4 w-4" />
          </div>

          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <p className="truncate text-sm font-medium">{asset.file_name}</p>
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusBadge domain="assetProcessing" value={asset.processing_status} />
              <StatusBadge domain="aiProfile" value={asset.ai_profile.status} />
              <StatusBadge domain="embedding" value={asset.ai_profile.embedding_status} />
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span className="tabular">{formatBytes(asset.file_size)}</span>
              <span>{formatRelativeTime(asset.created_at)}</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
