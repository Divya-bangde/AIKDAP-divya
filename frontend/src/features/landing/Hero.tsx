import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { KnowledgeNetwork } from "@/features/landing/KnowledgeNetwork";
import { heroReveal, landingItem, landingReveal } from "@/lib/motion";

/** The three words the product actually does, in order. Kept to three
 * so the eye reads them as one line of thought rather than a list. */
const ARC = ["Knowledge", "Intelligence", "Grounded insight"];

/**
 * Section 01 — the first screen.
 *
 * Loaded eagerly while the other eight sections are code-split away,
 * because this is the only part of the page a visitor actually waits
 * for.
 *
 * The reveal is orchestrated but bounded, and the call to action is a
 * real link in the first frame: nothing here ever makes someone wait
 * on an animation to use the page. There is no artificial loading
 * state, no fake progress, and no typed-out text.
 */
export function Hero() {
  return (
    <motion.section
      initial="hidden"
      animate="visible"
      variants={landingReveal}
      aria-label="AIKDAP"
      className="relative mx-auto flex min-h-[100svh] w-full max-w-6xl flex-col justify-center gap-16 px-6 pb-24 pt-32 md:px-10 lg:flex-row lg:items-center lg:justify-between lg:gap-20 lg:pb-32"
    >
      <div className="flex max-w-2xl flex-col items-start">
        <motion.p variants={landingItem} className="text-eyebrow uppercase text-ai">
          AI-Driven Knowledge Discovery
        </motion.p>

        <motion.h1
          variants={heroReveal}
          className="mt-7 font-display text-hero text-foreground"
        >
          AIKDAP
        </motion.h1>

        <motion.p
          variants={landingItem}
          className="mt-6 max-w-xl font-display text-headline text-foreground/75"
        >
          Knowledge discovery and analysis, grounded in your own documents.
        </motion.p>

        <motion.p
          variants={landingItem}
          className="mt-6 max-w-lg text-lede text-muted-foreground"
        >
          Upload what you already have. AIKDAP reads it, retrieves against it, reranks what it
          finds, and answers only from evidence it can show you.
        </motion.p>

        <motion.ul
          variants={landingItem}
          className="mt-10 flex flex-wrap items-center gap-x-3 gap-y-2"
        >
          {ARC.map((word, index) => (
            <li key={word} className="flex items-center gap-3">
              <span className="text-sm font-medium tracking-tight text-foreground/90">{word}</span>
              {index < ARC.length - 1 && (
                <ArrowRight aria-hidden="true" className="h-3.5 w-3.5 text-ai/70" />
              )}
            </li>
          ))}
        </motion.ul>

        <motion.div variants={landingItem} className="mt-12">
          <Link
            to="/login"
            className="group inline-flex items-center gap-3 rounded-xl bg-foreground px-7 py-4 font-display text-base font-medium tracking-tight text-background shadow-float transition-colors duration-200 hover:bg-primary hover:text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Enter AIKDAP
            <ArrowRight
              aria-hidden="true"
              className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1 motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
            />
          </Link>
        </motion.div>
      </div>

      <motion.div
        variants={landingItem}
        className="flex w-full max-w-lg shrink-0 items-center justify-center lg:w-[40%]"
      >
        <KnowledgeNetwork />
      </motion.div>

      {/* A quiet indication that the page continues. Decorative, so it
       * is hidden from assistive technology — a screen reader already
       * knows there are eight more sections. */}
      <motion.div
        aria-hidden="true"
        variants={landingItem}
        className="pointer-events-none absolute inset-x-0 bottom-8 hidden flex-col items-center gap-3 lg:flex"
      >
        <span className="text-eyebrow uppercase text-muted-foreground/70">Scroll</span>
        <span className="h-10 w-px overflow-hidden bg-border">
          <motion.span
            animate={{ y: ["-100%", "220%"] }}
            transition={{ duration: 2.2, ease: "easeInOut", repeat: Infinity, repeatDelay: 0.6 }}
            className="block h-4 w-px bg-ai motion-reduce:hidden"
          />
        </span>
      </motion.div>
    </motion.section>
  );
}
