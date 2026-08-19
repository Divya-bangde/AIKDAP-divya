import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnimatedNumber } from "@/components/motion/AnimatedNumber";

/** jsdom has no `matchMedia`, which is what Motion's `useReducedMotion`
 * reads. Installing a controllable stub lets the reduced-motion branch
 * be tested for real rather than assumed. */
function mockPrefersReducedMotion(prefers: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) => ({
      matches: query.includes("prefers-reduced-motion") ? prefers : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  );
}

describe("AnimatedNumber", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders nothing when the value is unknown, rather than a fabricated zero", () => {
    mockPrefersReducedMotion(false);
    const { container } = render(<AnimatedNumber value={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("settles on the exact backend value", async () => {
    mockPrefersReducedMotion(false);
    render(<AnimatedNumber value={42} />);
    await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());
  });

  it("skips the count-up entirely when reduced motion is requested", () => {
    mockPrefersReducedMotion(true);
    render(<AnimatedNumber value={17} />);
    // Present immediately, on the first render — no interpolation.
    expect(screen.getByText("17")).toBeInTheDocument();
  });
});
