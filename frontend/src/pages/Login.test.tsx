import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Login } from "@/pages/Login";
import * as authService from "@/services/auth";
import { useAuthStore } from "@/store/auth-store";
import { renderWithProviders } from "@/test/render";

vi.mock("@/services/auth");

describe("Login page", () => {
  afterEach(() => {
    useAuthStore.getState().clear();
    vi.restoreAllMocks();
  });

  it("renders the AIKDAP branding and the login form", () => {
    renderWithProviders(<Login />);

    expect(screen.getByRole("heading", { name: "AIKDAP" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("stores the session and does not show an error on successful login", async () => {
    vi.mocked(authService.login).mockResolvedValue({
      access_token: "access-123",
      refresh_token: "refresh-123",
      token_type: "bearer",
    });
    const user = userEvent.setup();

    renderWithProviders(<Login />);
    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(useAuthStore.getState().accessToken).toBe("access-123");
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a human-readable error and does not store a session on failed login", async () => {
    vi.mocked(authService.login).mockRejectedValue({
      status: 401,
      message: "Incorrect email or password.",
    });
    const user = userEvent.setup();

    renderWithProviders(<Login />);
    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Incorrect email or password.",
    );
    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});
