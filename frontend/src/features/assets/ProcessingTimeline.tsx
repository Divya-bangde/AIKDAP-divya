import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, Brain, Check, FileText, Layers, Loader2, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import { statusChange } from "@/lib/motion";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];

type StageState = "pending" | "active" | "done" | "failed" | "skipped";

/** Maps one backend status string onto a visual stage state.
 *
 * This is a rendering decision, not a judgement: each stage's state
 * comes from exactly one backend field, and no stage is ever marked
 * done because a *different* stage finished. There is no timer here
 * and no interpolation — if the backend has not said a stage
 * completed, this does not draw it as completed. */
function stageStates(asset: AssetRead): { key: string; label: string; model: string; state: StageState; icon: typeof FileText }[] {
  const processing = asset.processing_status;
  const profile = asset.ai_profile.status;
  const embedding = asset.ai_profile.embedding_status;

  const extractState: StageState =
    processing === "completed"
      ? "done"
      : processing === "failed"
        ? "failed"
        : processing === "unsupported"
          ? "skipped"
          : processing === "pending"
            ? "pending"
            : "active";

  const understandState: StageState =
    profile === "completed"
      ? "done"
      : profile === "failed"
        ? "failed"
        : profile === "unavailable"
          ? "skipped"
          : // Still "pending" on the backend: active only once extraction
            // actually finished, because that is when the model runs.
            extractState === "done"
            ? "active"
            : "pending";

  const embedState: StageState =
    embedding === "completed"
      ? "done"
      : embedding === "failed"
        ? "failed"
        : embedding === "not_applicable"
          ? "skipped"
          : embedding === "processing"
            ? "active"
            : extractState === "done"
              ? "active"
              : "pending";

  return [
    { key: "extract", label: "Extract & chunk", model: "Pipeline", state: extractState, icon: FileText },
    { key: "understand", label: "AI understanding", model: "Qwen 3.5", state: understandState, icon: Brain },
    { key: "embed", label: "Embedding", model: "BGE-M3", state: embedState, icon: Layers },
  ];
}

const STATE_STYLE: Record<StageState, string> = {
  done: "border-success/40 bg-success/10 text-success",
  active: "border-ai/40 bg-ai-soft text-ai",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  skipped: "border-border bg-muted text-muted-foreground",
  pending: "border-border bg-muted text-muted-foreground",
};

const STATE_LABEL: Record<StageState, string> = {
  done: "Completed",
  active: "Working",
  failed: "Failed",
  skipped: "Skipped",
  pending: "Waiting",
};

function StageIcon({ state, icon: Icon }: { state: StageState; icon: typeof FileText }) {
  if (state === "done") return <Check className="h-3.5 w-3.5" />;
  if (state === "active") return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
  if (state === "failed") return <AlertTriangle className="h-3.5 w-3.5" />;
  if (state === "skipped") return <Minus className="h-3.5 w-3.5" />;
  return <Icon className="h-3.5 w-3.5" />;
}

/** The document's real journey through the ingestion pipeline.
 *
 * Every stage's state is read from a backend field on each poll. No
 * percentage is shown anywhere, because the backend does not report
 * one — an indeterminate "working" indicator is the honest rendering
 * of "this is in progress, duration unknown". */
export function ProcessingTimeline({ asset }: { asset: AssetRead }) {
  const stages = stageStates(asset);

  return (
    <ol className="flex flex-col gap-0">
      {stages.map((stage, index) => (
        <li key={stage.key} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
                STATE_STYLE[stage.state],
                stage.state === "active" && "ai-pulse-ring",
              )}
            >
              <StageIcon state={stage.state} icon={stage.icon} />
            </div>
            {index < stages.length - 1 && (
              <div className="relative my-1 w-px flex-1 overflow-hidden bg-border">
                {/* A travelling highlight only while the NEXT stage is
                 * actually running — the connector shows real flow, it
                 * doesn't animate on a loop regardless of state. */}
                {stages[index + 1].state === "active" && (
                  <span className="ai-flow-line absolute inset-0" />
                )}
              </div>
            )}
          </div>

          <div className={cn("flex min-w-0 flex-1 items-center justify-between gap-3", index < stages.length - 1 && "pb-4")}>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium leading-tight">{stage.label}</p>
              <p className="truncate font-mono text-[10px] leading-tight text-muted-foreground">
                {stage.model}
              </p>
            </div>
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={stage.state}
                variants={statusChange}
                initial="hidden"
                animate="visible"
                exit="exit"
                className={cn(
                  "shrink-0 text-label uppercase",
                  stage.state === "done" && "text-success",
                  stage.state === "active" && "text-ai",
                  stage.state === "failed" && "text-destructive",
                  (stage.state === "pending" || stage.state === "skipped") &&
                    "text-muted-foreground",
                )}
              >
                {STATE_LABEL[stage.state]}
              </motion.span>
            </AnimatePresence>
          </div>
        </li>
      ))}
    </ol>
  );
}
