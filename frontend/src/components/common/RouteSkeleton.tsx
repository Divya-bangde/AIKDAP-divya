import { Skeleton } from "@/components/ui/skeleton";

/**
 * The frame of a routed page, shown while a code-split page chunk is
 * still arriving (Sprint 9K.6).
 *
 * Deliberately its own module rather than living beside the other
 * skeletons. This one is rendered by `RoutedPage`, which is part of the
 * application shell and therefore part of the *entry* chunk — so
 * anything sharing a module with it is pulled into the entry too.
 * Together in one file, the project-workspace and research-run
 * skeletons rode along and cost the initial payload ~1 kB gzipped for
 * code only a lazy route ever renders. Split, the entry carries just
 * this.
 *
 * Every page in the product opens with the same masthead — an eyebrow,
 * a display heading, a standfirst — so that much can honestly be drawn
 * before knowing which page is coming. Which page it *is* cannot be:
 * the chunk that would say so is the thing still loading, so the
 * heading says only that rather than guessing.
 */
export function RoutePendingSkeleton() {
  return (
    <>
      {/* Stands in for the page's own `<h1>` while it is absent — a page
       * with no level-one heading is a real axe violation
       * (`page-has-heading-one`). */}
      <h1 className="sr-only">Loading page</h1>
      <span role="status" className="sr-only">
        Loading page
      </span>
      <div aria-hidden="true" className="flex flex-col gap-8">
        <div>
          <Skeleton className="h-2.5 w-28" />
          <Skeleton className="mt-3 h-9 w-80 max-w-full" />
          <Skeleton className="mt-3 h-3.5 w-96 max-w-full" />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[104px] rounded-lg" />
          ))}
        </div>
      </div>
    </>
  );
}
