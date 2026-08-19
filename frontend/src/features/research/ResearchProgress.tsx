import { Check, CircleDashed, Loader2, SkipForward, X } from "lucide-react";

import type { components } from "@/types/api";

type ResearchStepRead = components["schemas"]["ResearchStepRead"];

const STEP_ICON: Record<string, typeof Check> = {
  completed: Check,
  running: Loader2,
  failed: X,
  skipped: SkipForward,
  pending: CircleDashed,
};

const STEP_STYLE: Record<string, string> = {
  completed: "border-success bg-success/10 text-success",
  running: "border-primary bg-primary/10 text-primary",
  failed: "border-destructive bg-destructive/10 text-destructive",
  skipped: "border-border bg-muted text-muted-foreground",
  pending: "border-border bg-muted text-muted-foreground",
};

/** Renders exactly the `steps[]` the backend returned, in order — no
 * step is assumed to exist, no elapsed-time-based inference, and a
 * skipped node is labeled "Skipped", never "Completed" (Phase 20). */
export function ResearchProgress({ steps }: { steps: ResearchStepRead[] }) {
  if (steps.length === 0) {
    return <p className="text-sm text-muted-foreground">Waiting for the run to start…</p>;
  }

  return (
    <ol className="flex flex-col gap-2">
      {steps
        .slice()
        .sort((a, b) => a.step_index - b.step_index)
        .map((step) => {
          const Icon = STEP_ICON[step.status] ?? CircleDashed;
          return (
            <li key={step.id} className="flex items-start gap-3">
              <span
                className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${STEP_STYLE[step.status] ?? STEP_STYLE.pending}`}
              >
                <Icon className={`h-3.5 w-3.5 ${step.status === "running" ? "animate-spin" : ""}`} />
              </span>
              <div className="flex-1">
                <p className="text-sm font-medium capitalize">{step.title}</p>
                {step.summary && (
                  <p className="text-xs text-muted-foreground">{step.summary}</p>
                )}
                {step.status === "failed" && step.error_message && (
                  <p className="text-xs text-destructive">{step.error_message}</p>
                )}
              </div>
              <span className="mt-0.5 shrink-0 text-xs capitalize text-muted-foreground">
                {step.status}
              </span>
            </li>
          );
        })}
    </ol>
  );
}
