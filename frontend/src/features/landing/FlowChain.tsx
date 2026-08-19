import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { diagramStage, inViewOnce } from "@/lib/motion";

export interface FlowNode {
  label: string;
  note?: string;
  /** Which semantic role this node plays. The roles are the product's,
   * held constant with the application UI: `ai` (cyan) is a model
   * doing work, `primary` (indigo) is the resulting artefact, and the
   * default is inert structure. */
  tone?: "default" | "ai" | "primary";
}

const TONE: Record<NonNullable<FlowNode["tone"]>, string> = {
  default: "border-border bg-card text-foreground",
  ai: "border-ai/35 bg-ai/[0.07] text-foreground",
  primary: "border-primary/40 bg-primary/[0.09] text-foreground",
};

const DOT: Record<NonNullable<FlowNode["tone"]>, string> = {
  default: "bg-muted-foreground/50",
  ai: "bg-ai",
  primary: "bg-primary",
};

/**
 * A left-to-right chain of named stages with drawn connectors — the
 * entry experience's workhorse architecture diagram.
 *
 * Every node is a real component or step of the platform, named the
 * way the codebase names it. Nothing here carries a number, a score,
 * a duration or a status: it is a labelled description of how the
 * system is put together, and it would look exactly the same on a
 * machine that had never run a single query. That distinction is the
 * whole point — the working application shows real telemetry, and this
 * page must never be mistaken for it.
 *
 * Rendered as an ordered list so the sequence is conveyed to a screen
 * reader by structure rather than by the arrow glyphs, which are
 * decorative and hidden. It wraps rather than scrolls on narrow
 * viewports, so nothing is ever cut off.
 */
export function FlowChain({
  nodes,
  className,
  align = "center",
}: {
  nodes: FlowNode[];
  className?: string;
  align?: "center" | "start";
}) {
  return (
    /* Below `sm` the chain becomes a column. Left as a wrapping row it
     * kept the right-pointing arrows while the nodes stacked, so the
     * diagram read as a list with arrows aimed at nothing — observed on
     * a 390px viewport. Stacked, the arrow rotates to point at the node
     * it actually leads to. */
    <ol
      className={cn(
        "flex flex-col gap-y-3 sm:flex-row sm:flex-wrap sm:items-stretch sm:gap-x-2",
        align === "center" ? "sm:justify-center" : "sm:justify-start",
        className,
      )}
    >
      {nodes.map((node, index) => (
        <motion.li
          key={node.label}
          initial="hidden"
          whileInView="visible"
          viewport={inViewOnce}
          variants={diagramStage(index)}
          className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center"
        >
          <div
            className={cn(
              "flex min-w-0 flex-col gap-1 rounded-lg border px-4 py-3 shadow-subtle",
              TONE[node.tone ?? "default"],
            )}
          >
            <span className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[node.tone ?? "default"])}
              />
              <span className="text-sm font-medium leading-tight">{node.label}</span>
            </span>
            {node.note && (
              <span className="pl-[14px] text-xs leading-tight text-muted-foreground">
                {node.note}
              </span>
            )}
          </div>

          {index < nodes.length - 1 && (
            <ArrowRight
              aria-hidden="true"
              className="h-4 w-4 shrink-0 rotate-90 self-center text-muted-foreground/45 sm:rotate-0"
            />
          )}
        </motion.li>
      ))}
    </ol>
  );
}
