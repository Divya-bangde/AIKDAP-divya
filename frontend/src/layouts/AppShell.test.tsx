import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/layouts/AppShell";
import * as authService from "@/services/auth";
import { useAuthStore } from "@/store/auth-store";
import { renderWithProviders } from "@/test/render";

vi.mock("@/services/auth");

describe("AppShell", () => {
  afterEach(() => {
    useAuthStore.getState().clear();
    vi.restoreAllMocks();
  });

  it("shows navigation links and clears the session on logout", async () => {
    useAuthStore.setState({ accessToken: "tok", refreshToken: "ref", user: null });
    vi.mocked(authService.currentUser).mockResolvedValue({
      id: "u1",
      email: "researcher@example.com",
      full_name: null,
      is_active: true,
      created_at: new Date().toISOString(),
    });
    const user = userEvent.setup();

    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>Dashboard content</div>} />
        </Route>
      </Routes>,
    );

    expect(screen.getAllByText("AIKDAP").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Dashboard")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Projects")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Research")[0]).toBeInTheDocument();
    expect(screen.getAllByText("System Health")[0]).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("researcher@example.com")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /log out/i }));

    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("moves one navigation indicator between links rather than swapping four", async () => {
    useAuthStore.setState({ accessToken: "tok", refreshToken: "ref", user: null });
    vi.mocked(authService.currentUser).mockResolvedValue({
      id: "u1",
      email: "researcher@example.com",
      full_name: null,
      is_active: true,
      created_at: new Date().toISOString(),
    });
    const user = userEvent.setup();

    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>Dashboard content</div>} />
          <Route path="/projects" element={<div>Projects content</div>} />
        </Route>
      </Routes>,
    );

    /* The indicator is a single element carrying a shared `layoutId`,
     * so Motion animates it from one link to the next. What a test can
     * hold onto is the invariant that makes that possible: exactly one
     * of them exists per navigation bar, and it lives inside whichever
     * link is currently active. */
    const indicator = () => document.querySelectorAll(".bg-accent.absolute");
    const dashboardLink = screen.getAllByRole("link", { name: "Dashboard" })[0];
    const projectsLink = screen.getAllByRole("link", { name: "Projects" })[0];

    await waitFor(() => expect(dashboardLink.querySelector(".bg-accent")).not.toBeNull());
    expect(projectsLink.querySelector(".bg-accent")).toBeNull();

    await user.click(projectsLink);

    await waitFor(() => expect(projectsLink.querySelector(".bg-accent")).not.toBeNull());
    expect(dashboardLink.querySelector(".bg-accent")).toBeNull();
    // One indicator per navigation bar (the shell renders a desktop and
    // a compact bar), never one per link.
    expect(indicator().length).toBe(2);
  });
});
