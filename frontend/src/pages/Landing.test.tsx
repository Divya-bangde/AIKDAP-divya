import { screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useApplyTheme } from "@/hooks/useTheme";
import { Landing } from "@/pages/Landing";
import { useThemeStore } from "@/store/theme-store";
import { renderWithProviders } from "@/test/render";

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

function Harness() {
  useApplyTheme();
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/elsewhere" element={<p>Elsewhere</p>} />
    </Routes>
  );
}

describe("Landing", () => {
  beforeEach(() => {
    useThemeStore.setState({ preference: null, override: null });
    document.documentElement.classList.remove("dark");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders the AIKDAP identity and an immediately usable CTA", () => {
    mockSystemDark(false);
    renderWithProviders(<Harness />, { route: "/" });

    expect(screen.getByRole("heading", { level: 1, name: "AIKDAP" })).toBeInTheDocument();
    // The CTA is a real link from the first render — never gated behind
    // an intro animation finishing.
    expect(screen.getByRole("link", { name: /enter aikdap/i })).toHaveAttribute("href", "/login");
  });

  it("forces dark even when the user's saved preference is light", async () => {
    mockSystemDark(false);
    useThemeStore.setState({ preference: "light", override: null });

    renderWithProviders(<Harness />, { route: "/" });

    await waitFor(() => {
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });
    // The user's real preference is untouched — only the transient
    // override is set, so entering the app returns them to light.
    expect(useThemeStore.getState().preference).toBe("light");
  });

  it("releases the dark override once the user leaves the landing", async () => {
    mockSystemDark(false);
    useThemeStore.setState({ preference: "light", override: null });

    const { unmount } = renderWithProviders(<Harness />, { route: "/" });
    await waitFor(() => expect(useThemeStore.getState().override).toBe("dark"));

    unmount();
    expect(useThemeStore.getState().override).toBeNull();
  });

  it("labels the knowledge-network motif as an illustration, not live data", () => {
    mockSystemDark(false);
    renderWithProviders(<Harness />, { route: "/" });

    const figure = screen.getByRole("img", { name: /illustration/i });
    expect(figure).toBeInTheDocument();
    expect(figure.getAttribute("aria-label")).toMatch(/converging through interpretation/i);
  });

  it("keeps the hero usable before the rest of the story has loaded", () => {
    mockSystemDark(false);
    renderWithProviders(<Harness />, { route: "/" });

    /* Sections 02–09 are a separate chunk. Nothing above the fold may
     * depend on it having arrived — the identity and the way in are
     * present in the very first render. */
    expect(screen.getByRole("heading", { level: 1, name: "AIKDAP" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /enter aikdap/i })).toBeEnabled();
  });

  it("tells the whole pipeline story, in the order the pipeline runs", async () => {
    mockSystemDark(false);
    renderWithProviders(<Harness />, { route: "/" });

    // Every section of the narrative is reachable by heading, so the
    // page reads in the same order to a screen reader as it does
    // visually.
    for (const heading of [
      /collecting information was never the hard part/i,
      /one pipeline\. seven stages/i,
      /every document is read before it is ever retrieved/i,
      /retrieval is a filter, not a search box/i,
      /an answer is only as good as the evidence/i,
      /the pipeline outlives any single provider/i,
      /the workspace shows its working/i,
      /turn information/i,
    ]) {
      expect(await screen.findByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
    }

    // The real stages, named as the backend names them, in order.
    const stages = await screen.findAllByRole("heading", { level: 3 });
    const names = stages.map((node) => node.textContent);
    expect(names.slice(0, 7)).toEqual([
      "Collect",
      "Understand",
      "Embed",
      "Retrieve",
      "Rerank",
      "Ground",
      "Synthesize",
    ]);
  });

  it("never presents its diagrams as measurements of a running system", async () => {
    mockSystemDark(false);
    renderWithProviders(<Harness />, { route: "/" });

    /* The two figures whose shape could be mistaken for telemetry each
     * disclaim it in the page itself, not merely in a code comment. */
    const retrieval = await screen.findByText(/illustration of the retrieval stages/i);
    expect(retrieval).toHaveTextContent(/not a measurement/i);
    expect(retrieval).toHaveTextContent(/no run is being reported/i);

    const providers = await screen.findByText(/the configured order of the gateway/i);
    expect(providers).toHaveTextContent(/does not report\s+which providers are reachable/i);

    /* And nothing on the page claims accuracy, speed or scale — the
     * numbers a marketing page reaches for and this one may not. */
    const page = document.body.textContent ?? "";
    expect(page).not.toMatch(/\d+\s*%/);
    expect(page).not.toMatch(/\baccuracy\b/i);
    expect(page).not.toMatch(/\b\d+(\.\d+)?\s*(ms|seconds?)\b/i);
    expect(page).not.toMatch(/\b\d[\d,]*\+?\s+(documents|users|customers|queries)\b/i);
  });
});
