import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "@/components/common/ThemeToggle";
import { useApplyTheme } from "@/hooks/useTheme";
import { useThemeStore } from "@/store/theme-store";
import { renderWithProviders } from "@/test/render";

/** jsdom has no `matchMedia`; this stub is what lets the OS-preference
 * fallback be tested for real rather than assumed. */
function mockSystemDark(prefersDark: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-color-scheme: dark") ? prefersDark : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

/** Mirrors the real app root, which mounts `useApplyTheme` once so the
 * resolved theme is written to <html>. */
function Harness() {
  useApplyTheme();
  return <ThemeToggle />;
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    useThemeStore.setState({ preference: null, override: null });
    document.documentElement.classList.remove("dark");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("falls back to the OS preference when the user has never chosen", () => {
    mockSystemDark(true);
    renderWithProviders(<Harness />);

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(useThemeStore.getState().preference).toBeNull();
  });

  it("follows a light OS preference just as readily", () => {
    mockSystemDark(false);
    renderWithProviders(<Harness />);

    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("lets an explicit choice override the OS preference", async () => {
    mockSystemDark(true);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: /switch to light theme/i }));

    expect(useThemeStore.getState().preference).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("names the action it will perform and reports the current state", async () => {
    mockSystemDark(false);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    const toggle = screen.getByRole("button", { name: /switch to dark theme/i });
    expect(toggle).toHaveAttribute("aria-pressed", "false");

    await user.click(toggle);

    const next = screen.getByRole("button", { name: /switch to light theme/i });
    expect(next).toHaveAttribute("aria-pressed", "true");
  });

  it("reveals the new theme from its own centre, including from the keyboard", async () => {
    mockSystemDark(false);
    /* The button reports its geometry rather than the pointer's, so a
     * keyboard press — which has no pointer at all — produces exactly
     * the same reveal as a click. */
    vi.spyOn(HTMLButtonElement.prototype, "getBoundingClientRect").mockReturnValue({
      left: 1000,
      top: 20,
      width: 36,
      height: 36,
      right: 1036,
      bottom: 56,
      x: 1000,
      y: 20,
      toJSON: () => ({}),
    });
    const animate = vi.fn();
    Object.defineProperty(document.documentElement, "animate", {
      value: animate,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(document, "startViewTransition", {
      value: (callback: () => void) => {
        callback();
        return { ready: Promise.resolve() };
      },
      configurable: true,
      writable: true,
    });

    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.tab();
    await user.keyboard("{Enter}");

    await vi.waitFor(() => expect(animate).toHaveBeenCalled());
    expect(animate.mock.calls[0][0].clipPath[0]).toBe("circle(0px at 1018px 38px)");
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    Reflect.deleteProperty(document, "startViewTransition");
    Reflect.deleteProperty(document.documentElement, "animate");
  });

  it("persists the explicit choice so it survives a reload", async () => {
    mockSystemDark(false);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: /switch to dark theme/i }));

    // Zustand's persist middleware writes synchronously to localStorage.
    const stored = JSON.parse(localStorage.getItem("aikdap-theme") ?? "{}");
    expect(stored.state.preference).toBe("dark");
    // The transient landing override must never be persisted.
    expect(stored.state.override).toBeUndefined();
  });
});
