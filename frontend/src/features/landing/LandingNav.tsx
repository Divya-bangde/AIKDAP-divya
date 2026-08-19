import { motion, useScroll, useSpring, useTransform } from "motion/react";
import { Link } from "react-router-dom";

const SECTIONS = [
  { href: "#pipeline", label: "Pipeline" },
  { href: "#grounding", label: "Grounding" },
  { href: "#resilience", label: "Resilience" },
];

/**
 * The entry experience's fixed header.
 *
 * Two jobs. It keeps the wordmark and the way in on screen at all
 * times, so a reader eight sections deep never has to scroll back to
 * act. And it carries a progress line across the very top of the
 * viewport, which is the only honest way to tell someone how much
 * document is left on a page this long.
 *
 * The header starts transparent over the hero and gains a background
 * only once the reader has moved past it — derived from real scroll
 * position, not from a timer.
 *
 * The section links are plain in-page anchors, so they work with the
 * browser's own scrolling, are keyboard reachable, and survive being
 * opened in a new tab. Nothing here hijacks the wheel.
 */
export function LandingNav() {
  const { scrollYProgress, scrollY } = useScroll();

  /* Springing the progress value stops the bar from twitching on a
   * trackpad while still reaching exactly 100% at the end. */
  const progress = useSpring(scrollYProgress, { stiffness: 120, damping: 30, mass: 0.3 });

  /* Fades the header's own surface in across the first 120px of
   * scroll — enough to clear the hero, short enough that it has
   * already happened by the time the second section arrives. */
  const surface = useTransform(scrollY, [0, 120], [0, 1]);

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <motion.div
        aria-hidden="true"
        style={{ opacity: surface }}
        className="absolute inset-0 border-b border-border/60 bg-background/80 backdrop-blur-md"
      />

      {/* Reading progress. Decorative — the same information is
       * available from the scrollbar — so it is hidden from assistive
       * technology rather than announced as a live region. */}
      <motion.div
        aria-hidden="true"
        style={{ scaleX: progress, originX: 0 }}
        className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-ai to-primary"
      />

      <nav
        aria-label="Page"
        className="relative mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5 md:px-10"
      >
        <Link
          to="/"
          className="flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span
            aria-hidden="true"
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary font-display text-sm font-semibold text-primary-foreground"
          >
            A
          </span>
          <span className="font-display text-base font-medium tracking-tight text-foreground">
            AIKDAP
          </span>
        </Link>

        <div className="flex items-center gap-1">
          <ul className="mr-2 hidden items-center gap-1 md:flex">
            {SECTIONS.map((section) => (
              <li key={section.href}>
                <a
                  href={section.href}
                  className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {section.label}
                </a>
              </li>
            ))}
          </ul>

          <Link
            to="/login"
            className="rounded-md border border-border-strong px-4 py-2 text-sm font-medium text-foreground transition-colors hover:border-primary hover:bg-primary hover:text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Sign in
          </Link>
        </div>
      </nav>
    </header>
  );
}
