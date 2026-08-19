import { AnimatePresence, motion } from "motion/react";
import { Loader2 } from "lucide-react";
import { Suspense } from "react";
import { useLocation, useOutlet } from "react-router-dom";

import { routeTransition } from "@/lib/motion";

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

  return (
    <div className="grid">
      {/* `initial={false}` so the first page after login appears
       * immediately rather than fading in behind the shell — the login
       * transition has already covered that moment. */}
      <AnimatePresence initial={false}>
        <motion.div
          key={location.pathname}
          variants={routeTransition}
          initial="hidden"
          animate="visible"
          exit="exit"
          style={{ gridArea: "1 / 1" }}
          className="min-w-0"
        >
          {/* Pages are code-split, so this catches the frame where a
           * chunk is still loading. Inside the transition, so the
           * fallback participates in it rather than flashing. */}
          <Suspense
            fallback={
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin text-ai" />
                Loading…
              </div>
            }
          >
            {outlet}
          </Suspense>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
