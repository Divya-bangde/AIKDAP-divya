import { AlertTriangle } from "lucide-react";

import { messageFor } from "@/lib/api-error";

interface ErrorStateProps {
  error: unknown;
  title?: string;
}

/** One reusable error state (Phase 23). Renders `messageFor(error)` —
 * always a human-readable string, never a stack trace, SQL error, or
 * credential (see `lib/api-error.ts`). */
export function ErrorState({ error, title = "Something went wrong" }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 py-16 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
        <AlertTriangle className="h-6 w-6 text-destructive" />
      </div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="max-w-sm text-sm text-muted-foreground">{messageFor(error)}</p>
    </div>
  );
}
