import { motion } from "motion/react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { inViewOnce, sectionItem, sectionReveal } from "@/lib/motion";

/**
 * One chapter of the entry experience's scrolling narrative.
 *
 * The editorial composition is the same every time — an indexed
 * eyebrow, a large display heading, an optional standfirst, then the
 * content — because a repeated frame is what turns nine sections into
 * one document instead of nine unrelated screens. The generous
 * vertical rhythm is deliberate whitespace, not padding left over from
 * a template.
 *
 * Headings are real `<h2>` elements inside a `<section>` with an
 * accessible name, so the whole page is navigable by heading in a
 * screen reader in exactly the order it reads visually. The index
 * ("01", "02") is decorative and hidden from assistive technology —
 * it is a typographic device, not content.
 *
 * Content arrives as the section scrolls in, once, and never
 * re-animates on the way back up.
 */
export function LandingSection({
  id,
  index,
  eyebrow,
  heading,
  standfirst,
  children,
  className,
}: {
  id?: string;
  index: string;
  eyebrow: string;
  heading: ReactNode;
  standfirst?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <motion.section
      id={id}
      initial="hidden"
      whileInView="visible"
      viewport={inViewOnce}
      variants={sectionReveal}
      aria-label={eyebrow}
      /* `scroll-mt` keeps a jumped-to heading clear of the fixed
       * header, which would otherwise cover it. */
      className={cn("relative scroll-mt-20 border-t border-border/60 py-24 md:py-32", className)}
    >
      <div className="mx-auto w-full max-w-6xl px-6 md:px-10">
        <motion.div variants={sectionItem} className="flex items-baseline gap-4">
          <span aria-hidden="true" className="font-mono text-eyebrow text-ai">
            {index}
          </span>
          <span className="text-eyebrow uppercase text-muted-foreground">{eyebrow}</span>
        </motion.div>

        <motion.h2
          variants={sectionItem}
          className="mt-6 max-w-3xl font-display text-editorial text-foreground"
        >
          {heading}
        </motion.h2>

        {standfirst && (
          <motion.div
            variants={sectionItem}
            className="mt-6 max-w-2xl text-lede text-muted-foreground"
          >
            {standfirst}
          </motion.div>
        )}

        {children && <div className="mt-14 md:mt-20">{children}</div>}
      </div>
    </motion.section>
  );
}

/** A child of a `LandingSection` that should arrive with the rest of
 * the section's contents. Exported so diagrams can join the same
 * stagger rather than starting their own. */
export function LandingItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div variants={sectionItem} className={className}>
      {children}
    </motion.div>
  );
}
