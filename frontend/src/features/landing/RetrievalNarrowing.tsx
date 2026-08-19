import { motion } from "motion/react";

import { cn } from "@/lib/utils";
import { inViewOnce } from "@/lib/motion";

/** Three columns, each keeping fewer passages than the last. The
 * counts are a *composition* — chosen so the narrowing is legible at a
 * glance — and are stated as such in the caption below the figure.
 * They are not measurements, and no real run is being described. */
const COLUMNS = [
  { label: "Retrieved", total: 12, kept: 12, tone: "muted" as const },
  { label: "Reranked", total: 12, kept: 6, tone: "ai" as const },
  { label: "Past the gate", total: 12, kept: 3, tone: "primary" as const },
];

const KEPT_TONE = {
  muted: "bg-muted-foreground/45",
  ai: "bg-ai",
  primary: "bg-primary",
};

/**
 * The shape of retrieval: many passages in, few passages out.
 *
 * This is the one figure on the page that could most easily be
 * mistaken for telemetry, so it is the one most carefully labelled.
 * The application has a real version of this — the evidence funnel on
 * a research run, which reads its numbers from the backend's step
 * payloads. This is the diagram of the idea. The caption says so, in
 * the page, not just in this comment.
 *
 * The dropped passages stay on screen at low contrast rather than
 * disappearing, because "these were considered and set aside" is the
 * actual message; showing only the survivors would tell the opposite
 * story.
 */
export function RetrievalNarrowing() {
  return (
    <figure>
      <div className="grid gap-8 sm:grid-cols-3 sm:gap-6">
        {COLUMNS.map((column, columnIndex) => (
          <div key={column.label} className="flex flex-col gap-4">
            <div className="flex items-baseline justify-between gap-2 border-b border-border/70 pb-2">
              <span className="text-label uppercase text-muted-foreground">{column.label}</span>
            </div>

            <ul aria-hidden="true" className="flex flex-wrap gap-1.5">
              {Array.from({ length: column.total }, (_, index) => {
                const kept = index < column.kept;
                return (
                  <motion.li
                    key={index}
                    initial={{ opacity: 0, scale: 0.4 }}
                    whileInView={{ opacity: kept ? 1 : 0.14, scale: 1 }}
                    viewport={inViewOnce}
                    transition={{
                      duration: 0.35,
                      delay: columnIndex * 0.18 + index * 0.025,
                      ease: [0.22, 1, 0.36, 1],
                    }}
                    className={cn(
                      "h-5 w-5 rounded",
                      kept ? KEPT_TONE[column.tone] : "bg-foreground/25",
                    )}
                  />
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <figcaption className="mt-8 border-l-2 border-ai/40 pl-4 text-sm leading-relaxed text-muted-foreground">
        Illustration of the retrieval stages. The quantities shown are chosen to make the
        narrowing legible — they are not a measurement, and no run is being reported. Real
        counts for a real question appear on that question&rsquo;s research run inside the
        platform.
      </figcaption>
    </figure>
  );
}
