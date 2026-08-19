import { FileText } from "lucide-react";

import { StatusBadge } from "@/components/common/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];

interface DocumentCardProps {
  asset: AssetRead;
  isSelected: boolean;
  onSelect: () => void;
}

export function DocumentCard({ asset, isSelected, onSelect }: DocumentCardProps) {
  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect();
      }}
      className={`cursor-pointer transition-colors ${
        isSelected ? "border-primary ring-1 ring-primary" : "hover:border-primary/50"
      }`}
    >
      <CardContent className="flex items-start gap-3 p-4">
        <FileText className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <p className="truncate text-sm font-medium">{asset.file_name}</p>
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge domain="assetProcessing" value={asset.processing_status} />
            <StatusBadge domain="aiProfile" value={asset.ai_profile.status} />
            <StatusBadge domain="embedding" value={asset.ai_profile.embedding_status} />
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{formatBytes(asset.file_size)}</span>
            <span>{formatRelativeTime(asset.created_at)}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
