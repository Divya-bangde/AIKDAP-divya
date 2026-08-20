import { AnimatePresence, motion } from "motion/react";
import { Suspense, useEffect, useRef } from "react";
import { useLocation, useOutlet } from "react-router-dom";

import { RoutePendingSkeleton } from "@/components/common/RouteSkeleton";
import { routeTransition } from "@/lib/motion";

/** Segment count of a path — `/` is 0, `/projects` is 1, `/projects/:id`
 * is 2. A cheap stand-in for "how deep in the workspace this route
 * is": exact for this app's actual route tree (dashboard → list →
 * detail), without needing a hand-maintained hierarchy table. */
function pathDepth(pathname: string): number {
  return pathname.split("/").filter(Boolean).length;
}

/** The previous render's value, updated after commit — the standard
 * safe pattern for reading "what was true last time" without mutating
 * a ref mid-render. Used to diff route depth across a navigation. */
function usePrevious<T>(value: T): T | undefined {
  const ref = useRef<T>();
  useEffect(() => {
    ref.current = value;
  });
  return ref.current;
}

/**
 * The animated content area of the application shell (Sprint 9K.4).
 *
 * Everything around this — sidebar, topbar, background texture — stays
 * mounted and perfectly still while it runs. That stillness is the
 * point: it is what makes navigating feel like moving *inside* one
 * application rather than loading a series of pages.
 *
 * Two implementation details are load-bearing:
 *
 * `useOutlet()` rather than `<Outlet />`. `AnimatePresence` keeps the
 * previous React element alive while it exits, and `useOutlet` returns
 * the routed element as a *value* — so the copy that is leaving keeps
 * rendering the page it was rendering. `<Outlet />` resolves against
 * the current route on every render, which would make the exiting copy
 * flip to the incoming page's content mid-exit.
 *
 * A CSS grid with both children in the same cell, rather than absolute
 * positioning. During the overlap both pages occupy one grid area, so
 * neither is taken out of flow: the container keeps a real height, the
 * scrollbar does not jump, and nothing has to be measured in JS.
 */
export function RoutedPage() {
  const location = useLocation();
  const outlet = useOutlet();

  const depth = pathDepth(location.pathname);
  const previousDepth = usePrevious(depth) ?? depth;
  const direction = Math.sign(depth - previousDepth);

  return (
    <div className="grid">
      {/* `initial={false}` so the first page after login appears
       * immediately rather than fading in behind the shell — the login
       * transition has already covered that moment. `custom` must also
       * sit on `AnimatePresence` itself, not just the child: it is what
       * lets the *exiting* copy still read this navigation's direction
       * rather than being stuck with whatever direction was current
       * when it mounted. */}
      <AnimatePresence initial={false} custom={direction}>
        <motion.div
          key={location.pathname}
          custom={direction}
          variants={routeTransition}
          initial="hidden"
          animate="visible"
          exit="exit"
          style={{ gridArea: "1 / 1" }}
          className="min-w-0"
        >
          {/* Pages are code-split, so this catches the frame where a
           * chunk is still loading. Inside the transition, so the
           * fallback participates in it rather than flashing.
           *
           * A page-shaped skeleton rather than the word "Loading…": every
           * page in the product opens with the same masthead, so drawing
           * that much is honest before knowing which page is arriving —
           * and it means the incoming page replaces a frame of roughly its
           * own size instead of a single line of text, which is what used
           * to make the content area jump on a slow chunk. */}
          <Suspense fallback={<RoutePendingSkeleton />}>{outlet}</Suspense>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
