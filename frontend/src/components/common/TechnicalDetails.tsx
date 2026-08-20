import { AnimatePresence, motion } from "motion/react";
import { ChevronDown } from "lucide-react";
import { useState, type ReactNode } from "react";

import { expandVariants } from "@/lib/motion";
import { cn } from "@/lib/utils";

/**
 * A collapsed-by-default disclosure for the technical layer underneath
 * a plain-language surface (Sprint 9K.8).
 *
 * The product's audience splits in two: an executive needs "Question →
 * Evidence → Answer" in about three seconds, and a technical reader
 * needs the real agent names, models, latencies and retrieval detail
 * in about ten. Neither is served by picking one and hiding the other
 * — the fix is progressive disclosure, not a fork of the page.
 *
 * Built as a single reusable primitive (used by `ResearchPipeline` per
 * step and by `ResearchResult` for the answer's provider/model detail)
 * so the accessible-disclosure contract is implemented once and tested
 * once rather than reinvented at each call site.
 *
 * Accessibility contract:
 * - A single real `<button>`, so Enter/Space and the focus ring are
 *   native rather than reimplemented.
 * - `aria-expanded` carries the state; the label stays constant
 *   ("Technical details") rather than flipping to "Hide technical
 *   details" — a stable accessible name is what lets a screen-reader
 *   user re-find the same control on the next step without its name
 *   having changed under them.
 * - `aria-controls` points at the content region's real `id`, built
 *   from the caller's own unique `id` so multiple instances on one
 *   page (six pipeline steps plus the answer card) never collide.
 * - No nested interactive control: the button contains only text and a
 *   decorative, `aria-hidden` chevron — nothing inside it is itself
 *   focusable.
 *
 * Collapsed content is unmounted, not merely hidden, matching the
 * pattern already used for the metrics block this replaces — an
 * `aria-controls` target that doesn't exist in the DOM while closed is
 * a standard, accepted disclosure pattern, not an ARIA violation.
 */
export function TechnicalDetails({
  id,
  children,
  className,
}: {
  /** Must be unique across the page — becomes the content region's id. */
  id: string;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const contentId = `${id}-technical-details`;

  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((value) => !value)}
        className="group inline-flex items-center gap-1.5 rounded-md py-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronDown
          aria-hidden="true"
          className={cn(
            "h-3 w-3 transition-transform duration-200 motion-reduce:transition-none",
            open && "rotate-180",
          )}
        />
        Technical details
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={contentId}
            variants={expandVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="overflow-hidden"
          >
            <div className="pt-2.5">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
