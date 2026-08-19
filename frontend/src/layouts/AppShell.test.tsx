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
});
