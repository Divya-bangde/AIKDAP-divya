import { motion } from "motion/react";
import {
  Brain,
  ChevronRight,
  FileText,
  Filter,
  Layers,
  ListOrdered,
  Quote,
  Sparkles,
} from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { staggerContainer, staggerItem } from "@/lib/motion";

/** The stages every AIKDAP research run passes through, with the real
 * model or mechanism behind each one. */
const STAGES = [
  { icon: FileText, label: "Document", detail: "Extract & chunk" },
  { icon: Brain, label: "Understanding", detail: "Qwen 3.5" },
  { icon: Layers, label: "Embedding", detail: "BGE-M3" },
  { icon: ListOrdered, label: "Retrieval", detail: "pgvector" },
  { icon: Filter, label: "Reranking", detail: "BGE-Reranker-v2-m3" },
  { icon: Sparkles, label: "Relevance gate", detail: "Threshold" },
  { icon: Quote, label: "Grounded synthesis", detail: "Cited answer" },
];

/** A description of the platform's architecture — deliberately NOT a
 * live activity feed.
 *
 * Nothing here is backed by per-run state, and nothing here claims to
 * be: it names the fixed sequence of stages and the real model behind
 * each, which is a property of the system rather than a measurement of
 * it. Live, per-run stage state is rendered by `ResearchPipeline` on
 * the research page, from the backend's own `steps[]`. */
export function PipelineOverview() {
  return (
    <Card className="overflow-hidden">
      <CardContent className="p-5">
        <div className="mb-4 flex items-baseline justify-between gap-3">
          <h3 className="text-section">Intelligence pipeline</h3>
          <p className="text-xs text-muted-foreground">
            How every research run is executed
          </p>
        </div>

        <motion.ol
          initial="hidden"
          animate="visible"
          variants={staggerContainer}
          className="flex flex-wrap items-stretch gap-1"
        >
          {STAGES.map(({ icon: Icon, label, detail }, index) => (
            <motion.li
              key={label}
              variants={staggerItem}
              className="flex min-w-0 flex-1 items-center gap-1"
            >
              <div className="group flex min-w-0 flex-1 flex-col gap-1.5 rounded-lg border border-border bg-sunken px-3 py-3 transition-colors hover:border-border-strong">
                <Icon className="h-4 w-4 text-ai transition-transform duration-200 group-hover:scale-110" />
                <span className="truncate text-xs font-medium leading-tight">{label}</span>
                <span className="truncate font-mono text-[10px] leading-tight text-muted-foreground">
                  {detail}
                </span>
              </div>
              {index < STAGES.length - 1 && (
                <ChevronRight
                  aria-hidden="true"
                  className="hidden h-3.5 w-3.5 shrink-0 text-muted-foreground/50 xl:block"
                />
              )}
            </motion.li>
          ))}
        </motion.ol>
      </CardContent>
    </Card>
  );
}
