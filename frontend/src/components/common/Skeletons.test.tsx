import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RoutePendingSkeleton } from "@/components/common/RouteSkeleton";
import {
  ProjectGridSkeleton,
  ProjectWorkspaceSkeleton,
  ResearchRunSkeleton,
  RowListSkeleton,
} from "@/components/common/Skeletons";

/** `heading` is the level-one heading a *whole-page* skeleton must
 * supply, because it stands in for a page that would otherwise own
 * one. Partial skeletons sit inside a page that still has its own
 * `<h1>`, so they must not add a second. */
const SKELETONS = [
  ["ProjectGridSkeleton", <ProjectGridSkeleton key="a" />, "Loading projects", null],
  [
    "ProjectWorkspaceSkeleton",
    <ProjectWorkspaceSkeleton key="b" />,
    "Loading project workspace",
    "Project workspace",
  ],
  ["ResearchRunSkeleton", <ResearchRunSkeleton key="c" />, "Loading research run", "Research run"],
  ["RoutePendingSkeleton", <RoutePendingSkeleton key="d" />, "Loading page", "Loading page"],
  [
    "RowListSkeleton",
    <RowListSkeleton key="e" label="Loading research history" />,
    "Loading research history",
    null,
  ],
] as const;

describe("shape-matched skeletons", () => {
  it.each(SKELETONS)("%s announces itself exactly once", (_name, element, label) => {
    render(element);

    const statuses = screen.getAllByRole("status");
    expect(statuses).toHaveLength(1);
    expect(statuses[0]).toHaveTextContent(label);
  });

  it.each(SKELETONS)(
    "%s shows no content a reader could mistake for data",
    (_n, element, label, heading) => {
      const { container } = render(element);

      /* A loading state may describe *where* something will be, and what
       * kind of page is coming; it may never suggest *what is on it*.
       * Everything visible is an empty box — the only text in the whole
       * tree is the screen-reader status and the generic page heading, so
       * there is no name, count, score or status to be read as real and
       * then contradicted a moment later. */
      const text = (container.textContent ?? "")
        .replace(label, "")
        .replace(heading ?? "", "")
        .trim();
      expect(text).toBe("");
      expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    },
  );

  it.each(SKELETONS)(
    "%s supplies a level-one heading only when it replaces a whole page",
    (_n, element, _label, heading) => {
      render(element);

      /* A skeleton standing in for a whole page must carry that page's
       * `<h1>` — axe reports `page-has-heading-one` otherwise, which is
       * how this was caught on the project workspace. One that sits
       * inside a page must not, or the page ends up with two. */
      const headings = screen.queryAllByRole("heading", { level: 1 });
      if (heading === null) {
        expect(headings).toHaveLength(0);
      } else {
        expect(headings).toHaveLength(1);
        expect(headings[0]).toHaveTextContent(heading);
        // Named for the kind of page, never for a subject it cannot know.
        expect(headings[0]).toHaveClass("sr-only");
      }
    },
  );

  it.each(SKELETONS)("%s hides its decorative geometry from assistive tech", (_n, element) => {
    const { container } = render(element);

    /* The boxes are noise to a screen reader — the `role="status"`
     * message above already said "loading" in words. Every visual
     * subtree is therefore behind `aria-hidden`. */
    const pulses = [...container.querySelectorAll(".animate-pulse")];
    expect(pulses.length).toBeGreaterThan(0);
    for (const pulse of pulses) {
      expect(pulse.closest("[aria-hidden='true']")).not.toBeNull();
    }
  });
});
