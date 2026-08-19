import { motion } from "motion/react";
import { Filter } from "lucide-react";

import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import { Card, CardContent } from "@/components/ui/card";
import { evidenceFunnel } from "@/features/research/step-metrics";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { Citation } from "@/types/citation";
import type { components } from "@/types/api";

type ResearchStepRead = components["schemas"]["ResearchStepRead"];

/** How evidence narrowed from retrieval to the citations in the answer.
 *
 * Each stage is one real number from one real backend field (see
 * `evidenceFunnel`), and stages whose source field is absent are
 * simply not drawn. The bars are scaled against the largest stage in
 * *this* run — they are a relative visual aid, and the exact count is
 * always printed next to each one, so nothing depends on reading a bar
 * length. No stage is a percentage, because none of the underlying
 * fields is one. */
export function EvidenceFunnel({
  steps,
  citations,
}: {
  steps: ResearchStepRead[];
  citations: Citation[];
}) {
  const { stages, withheld } = evidenceFunnel(steps);
  if (stages.length === 0) return null;

  const max = Math.max(...stages.map((stage) => stage.value), 1);

  // The threshold each surviving chunk had to clear. Read off the
  // citations themselves (the backend records it per citation); shown
  // only when the backend actually supplied it.
  const threshold = citations.find(
    (citation) => typeof citation.relevance_threshold === "number",
  )?.relevance_threshold;

  return (
    <Card>
      <CardContent className="p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-ai" />
            <h3 className="text-section">Evidence funnel</h3>
          </div>
          {threshold !== undefined && (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-sunken px-2 py-1">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Relevance threshold
              </span>
              <span className="tabular text-[11px] font-medium">{threshold}</span>
            </span>
          )}
        </div>

        <motion.ol
          initial="hidden"
          animate="visible"
          variants={staggerContainer}
          className="flex flex-col gap-3"
        >
          {stages.map((stage, index) => (
            <motion.li key={stage.label} variants={staggerItem} className="flex items-center gap-3">
              <div className="w-36 shrink-0">
                <p className="text-xs font-medium leading-tight">{stage.label}</p>
                <p className="truncate text-[10px] leading-tight text-muted-foreground">
                  {stage.detail}
                </p>
              </div>

              <div className="h-7 flex-1 overflow-hidden rounded-md border border-border bg-sunken">
                {/* Driven by an inline transform + CSS transition rather
                 * than a Motion animation. This element is a leaf inside
                 * a variant-driven stagger tree, where a child's own
                 * `animate` object and the parent's propagated variant
                 * label both want to own the same property; a plain
                 * transform sidesteps that ambiguity entirely. It is
                 * equally compositor-friendly (no layout), and the
                 * global reduced-motion rule in `index.css` still
                 * collapses its transition to ~0ms. */}
                <div
                  style={{
                    transform: `scaleX(${stage.value / max})`,
                    transformOrigin: "left",
                    transition: `transform 500ms cubic-bezier(0.22, 1, 0.36, 1) ${index * 60}ms`,
                  }}
                  className="h-full rounded-md bg-gradient-to-r from-ai/70 to-ai"
                />
              </div>

              <AnimatedNumber
                value={stage.value}
                className="tabular w-8 shrink-0 text-right text-sm font-semibold"
              />
            </motion.li>
          ))}
        </motion.ol>

        {withheld !== undefined && withheld > 0 && (
          <p className="mt-4 border-t border-border pt-3 text-xs text-muted-foreground">
            <span className="font-medium text-warning">{withheld} simulated reference(s)</span>{" "}
            were retrieved but withheld from synthesis — they are placeholders from the mock web
            provider and contain no facts to ground an answer in.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
