import { AnimatePresence, motion } from "motion/react";

import { Badge } from "@/components/ui/badge";
import { statusChange } from "@/lib/motion";
import { statusBadge, type StatusDomain } from "@/lib/status";

/** Every surface that shows a run's (or step's, or asset's) outcome
 * renders it through this one component, so a value that changes while
 * someone is looking at it — a run going `running` → `grounded` under
 * `usePolling` — reads as a noticed state change rather than a silent
 * text swap. Keyed on `domain:value`, so a genuinely new outcome
 * re-triggers `statusChange` (Sprint 9K.9) while an unrelated re-render
 * with the same value does not. `initial={false}` on `AnimatePresence`
 * means the very first paint of a badge never animates — only a value
 * that changes after the badge already exists on screen does. */
export function StatusBadge({ domain, value }: { domain: StatusDomain; value: string }) {
  const { variant, label } = statusBadge(domain, value);
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={`${domain}:${value}`}
        variants={statusChange}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="inline-flex"
      >
        <Badge variant={variant} className="capitalize">{label}</Badge>
      </motion.span>
    </AnimatePresence>
  );
}
