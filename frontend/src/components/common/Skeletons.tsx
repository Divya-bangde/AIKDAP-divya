import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Shape-matched loading states (Sprint 9K.6).
 *
 * A loading state has one job: tell the reader what is about to be
 * there. A bare grey rectangle — or the word "Loading…" — does the
 * opposite, because it describes nothing and reserves a height that
 * the real content then disagrees with, so the page jumps when data
 * lands.
 *
 * Each skeleton below traces the component it stands in for: the same
 * card, the same border, the same row rhythm, the same tile grid. That
 * makes the arrival of real data a substitution rather than a
 * relayout, and it means the skeleton is wrong in an obvious, visible
 * way if the component it mirrors is ever restructured.
 *
 * These are deliberately *not* fabricated content. Nothing here shows
 * a number, a label, or a name — only the geometry of where one will
 * be. `Skeleton`'s own `animate-pulse` is a CSS animation, so the
 * global `prefers-reduced-motion` block in `index.css` already stops
 * it without any per-component handling.
 *
 * All of them are marked `aria-hidden` and paired with a visually
 * hidden status message: a screen reader is told "loading" once, in
 * words, instead of being walked through a dozen meaningless boxes.
 */
function Loading({ label, heading }: { label: string; heading?: string }) {
  return (
    <>
      {/* A skeleton that stands in for a *whole page* also stands in for
       * that page's `<h1>` — and a page with no level-one heading is a
       * real axe violation, which is exactly how this was caught
       * (`page-has-heading-one`, moderate, both themes, on the project
       * workspace's loading state).
       *
       * The heading names the kind of page, never its subject: the
       * project's name is precisely what is not known yet, and inventing
       * one to satisfy a heading rule would be fabricating the first
       * thing the reader sees. Partial skeletons pass no `heading`,
       * because the page they sit inside still owns its own. */}
      {heading && <h1 className="sr-only">{heading}</h1>}
      <span role="status" className="sr-only">
        {label}
      </span>
    </>
  );
}

/** Mirrors `ProjectCard` — icon tile, badge, title, two description
 * lines, a stat row, and the bordered footer. */
export function ProjectCardSkeleton() {
  return (
    <Card aria-hidden="true" className="h-full">
      <CardContent className="flex h-full flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <Skeleton className="h-10 w-10 rounded-lg" />
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
        <div className="flex-1">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="mt-2.5 h-3 w-full" />
          <Skeleton className="mt-1.5 h-3 w-4/5" />
        </div>
        <div className="flex items-center gap-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-28" />
        </div>
        <div className="flex items-center justify-between border-t border-border pt-3">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-24" />
        </div>
      </CardContent>
    </Card>
  );
}

export function ProjectGridSkeleton({ count = 3 }: { count?: number }) {
  return (
    <>
      <Loading label="Loading projects" />
      <div className="grid grid-cols-1 items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: count }, (_, i) => (
          <ProjectCardSkeleton key={i} />
        ))}
      </div>
    </>
  );
}

/** Mirrors `ProjectHeader` plus the tab bar and the four
 * `KnowledgeStat` tiles below it, so the workspace does not reflow
 * when the project resolves. */
export function ProjectWorkspaceSkeleton() {
  return (
    <>
      <Loading label="Loading project workspace" heading="Project workspace" />
      <div aria-hidden="true" className="flex flex-col gap-8">
        <div className="flex flex-col gap-4 border-b border-border pb-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-4">
              <Skeleton className="h-12 w-12 rounded-xl" />
              <div className="min-w-0 flex-1">
                <Skeleton className="h-6 w-52" />
                <Skeleton className="mt-2.5 h-3.5 w-72" />
                <Skeleton className="mt-2 h-3 w-32" />
              </div>
            </div>
            <Skeleton className="h-10 w-36 rounded-md" />
          </div>
        </div>

        <div className="flex flex-col gap-6">
          <div className="flex gap-1 border-b border-border pb-2.5">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-5 w-20" />
          </div>
          <div>
            <Skeleton className="mb-3 h-4 w-32" />
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="rounded-lg border border-border bg-sunken p-4">
                  <Skeleton className="h-2.5 w-16" />
                  <Skeleton className="mt-2.5 h-7 w-10" />
                  <Skeleton className="mt-2 h-2 w-14" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

/** A list of rows inside a card — the shape shared by the research
 * history list and the dashboard's recent-activity panels. */
export function RowListSkeleton({
  rows = 3,
  label,
  className,
}: {
  rows?: number;
  label: string;
  className?: string;
}) {
  return (
    <>
      <Loading label={label} />
      <Card aria-hidden="true" className={className}>
        <CardContent className="flex flex-col gap-1 p-3">
          {Array.from({ length: rows }, (_, i) => (
            <div key={i} className="flex items-center justify-between gap-3 px-3 py-2.5">
              <div className="flex min-w-0 flex-1 items-center gap-3">
                <Skeleton className="h-4 w-4 shrink-0 rounded" />
                <div className="min-w-0 flex-1">
                  <Skeleton className="h-3.5 w-3/5" />
                  <Skeleton className="mt-1.5 h-2.5 w-28" />
                </div>
              </div>
              <Skeleton className="h-5 w-20 shrink-0 rounded-full" />
            </div>
          ))}
        </CardContent>
      </Card>
    </>
  );
}

/** Mirrors `ResearchRunView`'s header card and the vertical
 * `ResearchPipeline` rail beneath it — including the connector line
 * between nodes, so the run view resolves into place rather than
 * replacing a spinner. */
export function ResearchRunSkeleton() {
  return (
    <>
      <Loading label="Loading research run" heading="Research run" />
      <div aria-hidden="true" className="flex flex-col gap-6">
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-3 border-b border-border bg-sunken/50 p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Skeleton className="h-2.5 w-28" />
                <Skeleton className="mt-2.5 h-6 w-3/4" />
              </div>
              <Skeleton className="h-5 w-24 shrink-0 rounded-full" />
            </div>
          </div>
          <CardContent className="pt-6">
            <Skeleton className="mb-5 h-2.5 w-36" />
            <ol className="flex flex-col">
              {[0, 1, 2, 3].map((i, index, all) => (
                <li key={i} className="flex gap-4">
                  <div className="flex flex-col items-center">
                    <Skeleton className="h-8 w-8 shrink-0 rounded-full" />
                    {index < all.length - 1 && (
                      <div className="my-1 w-px flex-1 bg-border" />
                    )}
                  </div>
                  <div className={cn("min-w-0 flex-1", index < all.length - 1 && "pb-5")}>
                    <div className="flex items-baseline justify-between gap-2">
                      <Skeleton className="h-3.5 w-40" />
                      <Skeleton className="h-2.5 w-16" />
                    </div>
                    <Skeleton className="mt-2 h-2.5 w-2/3" />
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

/* `RoutePendingSkeleton` deliberately lives in its own module
 * (`RouteSkeleton.tsx`): it is rendered by the application shell, so
 * anything sharing a file with it is pulled into the entry chunk.
 * Everything here is rendered only by a lazy route and must stay out
 * of the initial payload. */
