import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { RoutedPage } from "@/layouts/RoutedPage";
import { renderWithProviders } from "@/test/render";

function Shell() {
  return (
    <div>
      <nav>
        <Link to="/">Home</Link>
        <Link to="/second">Second</Link>
      </nav>
      <p data-testid="shell-marker">shell</p>
      <RoutedPage />
    </div>
  );
}

function Harness() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<h1>First page</h1>} />
        <Route path="/second" element={<h1>Second page</h1>} />
      </Route>
    </Routes>
  );
}

describe("RoutedPage", () => {
  it("renders the routed page inside the shell", async () => {
    renderWithProviders(<Harness />, { route: "/" });

    expect(await screen.findByText("First page")).toBeInTheDocument();
    expect(screen.getByTestId("shell-marker")).toBeInTheDocument();
  });

  it("swaps the page without ever unmounting the shell around it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: "/" });

    const shell = await screen.findByTestId("shell-marker");

    await user.click(screen.getByRole("link", { name: "Second" }));
    await waitFor(() => expect(screen.getByText("Second page")).toBeInTheDocument());

    /* Node identity, not just presence: if the shell had remounted, the
     * sidebar, header and their state would have been torn down and
     * rebuilt, which is exactly the "disconnected pages" feel the
     * transition exists to remove. */
    expect(screen.getByTestId("shell-marker")).toBe(shell);
  });

  it("keeps the outgoing page mounted while the incoming one arrives", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: "/" });
    await screen.findByText("First page");

    await user.click(screen.getByRole("link", { name: "Second" }));

    /* Both pages are briefly in the tree together. This is the property
     * that makes shared-element transitions possible at all — a
     * `layoutId` on a project card can only animate into the workspace
     * header if the card still exists when the header mounts. A
     * `mode="wait"` presence would unmount the source first and break
     * every one of them silently, so it is worth a test. */
    expect(screen.getByText("First page")).toBeInTheDocument();
    expect(screen.getByText("Second page")).toBeInTheDocument();

    // And the outgoing copy shows the page it was showing — not the
    // incoming route's content, which is what `<Outlet />` would give.
    await waitFor(() => expect(screen.queryByText("First page")).not.toBeInTheDocument());
  });
});
