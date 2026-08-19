import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyThemeAnimated } from "@/hooks/useTheme";

/** Installs a View Transitions API that behaves like a real one:
 * `startViewTransition` captures, runs the caller's callback, and
 * resolves `ready` afterwards. Returns handles so a test can assert
 * *when* things happened, not only that they happened. */
function mockViewTransitions() {
  const callbacks: (() => void)[] = [];
  const startViewTransition = vi.fn((callback: () => void) => {
    callbacks.push(callback);
    callback();
    return { ready: Promise.resolve() };
  });
  Object.defineProperty(document, "startViewTransition", {
    value: startViewTransition,
    configurable: true,
    writable: true,
  });
  return { startViewTransition, callbacks };
}

/** jsdom implements no Web Animations API on elements. */
function mockAnimate() {
  const animate = vi.fn();
  Object.defineProperty(document.documentElement, "animate", {
    value: animate,
    configurable: true,
    writable: true,
  });
  return animate;
}

function mockReducedMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion: reduce") ? reduce : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

const ORIGIN = { x: 1200, y: 40 };

describe("applyThemeAnimated", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
    mockReducedMotion(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(document, "startViewTransition");
    Reflect.deleteProperty(document.documentElement, "animate");
  });

  it("reveals the new theme outward from the origin it was given", async () => {
    const { startViewTransition } = mockViewTransitions();
    const animate = mockAnimate();
    const commit = vi.fn();

    applyThemeAnimated("dark", ORIGIN, commit);
    await vi.waitFor(() => expect(animate).toHaveBeenCalled());

    expect(startViewTransition).toHaveBeenCalledTimes(1);
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // The circle must grow from the control that was pressed, and it is
    // the *new* theme's snapshot being uncovered — not an overlay being
    // painted over the old one.
    const [keyframes, options] = animate.mock.calls[0];
    expect(keyframes.clipPath[0]).toBe(`circle(0px at ${ORIGIN.x}px ${ORIGIN.y}px)`);
    expect(keyframes.clipPath[1]).toMatch(
      new RegExp(`^circle\\(\\d+(\\.\\d+)?px at ${ORIGIN.x}px ${ORIGIN.y}px\\)$`),
    );
    expect(options.pseudoElement).toBe("::view-transition-new(root)");
  });

  it("keeps the reveal inside the brief's 300–600ms window", async () => {
    mockViewTransitions();
    const animate = mockAnimate();

    applyThemeAnimated("dark", ORIGIN, vi.fn());
    await vi.waitFor(() => expect(animate).toHaveBeenCalled());

    const duration = animate.mock.calls[0][1].duration;
    expect(duration).toBeGreaterThanOrEqual(300);
    expect(duration).toBeLessThanOrEqual(600);
  });

  it("switches instantly, with no animation, under reduced motion", () => {
    mockReducedMotion(true);
    const { startViewTransition } = mockViewTransitions();
    const animate = mockAnimate();
    const commit = vi.fn();

    applyThemeAnimated("dark", ORIGIN, commit);

    // The decoration is gone entirely — not shortened, not faded.
    expect(startViewTransition).not.toHaveBeenCalled();
    expect(animate).not.toHaveBeenCalled();
    // The theme still changes, which is the part that is not optional.
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("switches instantly in a browser without the View Transitions API", () => {
    const animate = mockAnimate();
    const commit = vi.fn();

    applyThemeAnimated("dark", ORIGIN, commit);

    expect(animate).not.toHaveBeenCalled();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("switches instantly when the caller has no origin to grow from", () => {
    const { startViewTransition } = mockViewTransitions();
    mockAnimate();
    const commit = vi.fn();

    applyThemeAnimated("dark", undefined, commit);

    expect(startViewTransition).not.toHaveBeenCalled();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("commits the preference inside the transition rather than before it", () => {
    const callbacks: (() => void)[] = [];
    Object.defineProperty(document, "startViewTransition", {
      value: (callback: () => void) => {
        // Deliberately does NOT run the callback, standing in for the
        // frame the browser spends capturing the outgoing snapshot.
        callbacks.push(callback);
        return { ready: Promise.resolve() };
      },
      configurable: true,
      writable: true,
    });
    mockAnimate();
    const commit = vi.fn();

    applyThemeAnimated("dark", ORIGIN, commit);

    /* If the preference were committed first, React's own apply-theme
     * effect would flip the class before the browser had captured the
     * "before" frame, and both snapshots would show the new theme —
     * the reveal would animate nothing. Nothing may have changed yet. */
    expect(commit).not.toHaveBeenCalled();
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    callbacks[0]();

    expect(commit).toHaveBeenCalledTimes(1);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
