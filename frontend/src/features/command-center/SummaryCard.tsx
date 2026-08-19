import type { LucideIcon } from "lucide-react";
import { motion } from "motion/react";

import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { hoverLift } from "@/lib/motion";
import { cn } from "@/lib/utils";

interface SummaryCardProps {
  icon: LucideIcon;
  label: string;
  value: number | undefined;
  isLoading: boolean;
  isError: boolean;
  /** Optional real, backend-derived context line (e.g. "3 grounded").
   * Never a trend, forecast, or invented comparison. */
  detail?: string;
  tone?: "default" | "ai" | "success";
}

const TONE: Record<string, string> = {
  default: "bg-accent text-accent-foreground",
  ai: "bg-ai-soft text-ai",
  success: "bg-success/10 text-success",
};

/** A hairline of the tile's own tone across its top edge — enough to
 * differentiate the four tiles at a glance without colouring whole
 * cards, which would make the dashboard read as a traffic light. */
const TONE_RULE: Record<string, string> = {
  default: "bg-primary/50",
  ai: "bg-ai/60",
  success: "bg-success/60",
};

/** A command-centre metric tile. Renders "Unavailable" rather than a
 * fabricated number if the underlying query failed (Phase 9: "Do NOT
 * fabricate statistics"), and counts up to the real value only once
 * that value has actually arrived. */
export function SummaryCard({
  icon: Icon,
  label,
  value,
  isLoading,
  isError,
  detail,
  tone = "default",
}: SummaryCardProps) {
  return (
    /* `h-full` on the motion wrapper too, not just the Card: without it
     * the wrapper collapses to its content and a tile carrying a
     * `detail` line renders taller than its neighbours, which reads as
     * a different surface rather than a taller one. */
    <motion.div {...hoverLift} className="h-full">
      <Card className="flex h-full flex-col overflow-hidden transition-shadow duration-200 hover:shadow-raised">
        <span aria-hidden="true" className={cn("h-0.5 w-full", TONE_RULE[tone])} />
        <CardContent className="flex flex-1 items-start gap-4 p-5">
          <div
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
              TONE[tone],
            )}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-label uppercase text-muted-foreground">{label}</p>
            {isLoading ? (
              <Skeleton className="mt-2 h-8 w-14" />
            ) : isError ? (
              <p className="mt-1 text-sm text-muted-foreground">Unavailable</p>
            ) : (
              <AnimatedNumber
                value={value}
                className="tabular mt-0.5 block text-3xl font-semibold tracking-tight"
              />
            )}
            {detail && !isLoading && !isError && (
              <p className="mt-1 truncate text-xs text-muted-foreground">{detail}</p>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
