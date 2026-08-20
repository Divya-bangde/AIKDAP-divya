import { motion } from "motion/react";
import { Link } from "react-router-dom";

import { AikdapMark } from "@/components/common/AikdapMark";
import { inViewOnce, sectionItem, sectionReveal } from "@/lib/motion";

/** In-page anchors only. Every destination below exists — either a
 * section of this document or a route in the application — because a
 * footer full of links to nothing is the fastest way to make a product
 * site read as a template. */
const COLUMNS: { title: string; links: { label: string; href: string }[] }[] = [
  {
    title: "How it works",
    links: [
      { label: "The pipeline", href: "#pipeline" },
      { label: "Grounded answers", href: "#grounding" },
      { label: "Provider resilience", href: "#resilience" },
    ],
  },
];

/** What the platform is built on. Named exactly as the codebase names
 * them — these are the real models and stores behind the pipeline
 * described above, not a logo wall. */
const STACK = ["Qwen 3.5", "BGE-M3", "BGE-Reranker-v2-m3", "pgvector", "LangGraph", "FastAPI"];

/**
 * The end of the entry experience (Sprint 9K.6).
 *
 * The page previously stopped dead at its closing call to action: the
 * document ran out rather than concluding, which on a nine-section
 * scroll reads as an unfinished page. A footer gives the narrative a
 * floor to land on, and gives a reader who has scrolled past every
 * section a second place to find the way in without scrolling back up.
 *
 * It restates identity and nothing else. There is no fabricated
 * company detail here — no address, no invented copyright holder, no
 * social accounts that do not exist, no newsletter that nothing is
 * listening to. What it carries is the wordmark, the one sentence that
 * describes the product, real in-page links, and the real names of the
 * models the pipeline runs on.
 */
export function LandingFooter() {
  return (
    <motion.footer
      initial="hidden"
      whileInView="visible"
      viewport={inViewOnce}
      variants={sectionReveal}
      className="relative border-t border-border/60 bg-background/40"
    >
      <div className="mx-auto w-full max-w-6xl px-6 py-16 md:px-10 md:py-20">
        <div className="flex flex-col gap-12 md:flex-row md:justify-between md:gap-16">
          <motion.div variants={sectionItem} className="max-w-sm">
            <Link
              to="/"
              className="inline-flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <AikdapMark className="h-8 w-8 rounded-lg" />
              <span className="font-display text-base font-medium tracking-tight text-foreground">
                AIKDAP
              </span>
            </Link>
            <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
              AI-Driven Knowledge Discovery &amp; Analysis Platform. Answers grounded in your own
              documents, traceable to the passage they came from.
            </p>
          </motion.div>

          <motion.div
            variants={sectionItem}
            className="flex flex-col gap-10 sm:flex-row sm:gap-16"
          >
            {COLUMNS.map((column) => (
              <div key={column.title}>
                <h2 className="text-label uppercase text-muted-foreground">{column.title}</h2>
                <ul className="mt-4 flex flex-col gap-2.5">
                  {column.links.map((link) => (
                    <li key={link.href}>
                      <a
                        href={link.href}
                        className="rounded-sm text-sm text-foreground/80 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      >
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            <div>
              <h2 className="text-label uppercase text-muted-foreground">Get started</h2>
              <ul className="mt-4 flex flex-col gap-2.5">
                <li>
                  <Link
                    to="/login"
                    className="rounded-sm text-sm text-foreground/80 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    Sign in
                  </Link>
                </li>
                <li>
                  <Link
                    to="/login"
                    className="rounded-sm text-sm text-foreground/80 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    Create an account
                  </Link>
                </li>
              </ul>
            </div>
          </motion.div>
        </div>

        <motion.div
          variants={sectionItem}
          className="mt-14 flex flex-col gap-5 border-t border-border/60 pt-8 md:flex-row md:items-center md:justify-between"
        >
          <ul className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
            {STACK.map((item) => (
              <li
                key={item}
                className="rounded-md border border-border/70 px-2 py-1 font-mono text-[11px] text-muted-foreground"
              >
                {item}
              </li>
            ))}
          </ul>
          <p className="shrink-0 text-xs text-muted-foreground">
            Built as an AI work operating system.
          </p>
        </motion.div>
      </div>
    </motion.footer>
  );
}
