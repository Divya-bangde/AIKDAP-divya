import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { ProtectedRoute } from "@/components/common/ProtectedRoute";
import { useAuthStore } from "@/store/auth-store";

function renderProtected() {
  return render(
    <MemoryRouter initialEntries={["/projects"]}>
      <Routes>
        <Route path="/login" element={<div>Login Page</div>} />
        <Route element={<ProtectedRoute />}>
          <Route path="/projects" element={<div>Projects Page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  afterEach(() => {
    useAuthStore.getState().clear();
  });

  it("redirects an unauthenticated visitor to /login", () => {
    useAuthStore.setState({ accessToken: null, refreshToken: null, user: null });

    renderProtected();

    expect(screen.getByText("Login Page")).toBeInTheDocument();
    expect(screen.queryByText("Projects Page")).not.toBeInTheDocument();
  });

  it("renders the protected content when a session exists", () => {
    useAuthStore.setState({ accessToken: "tok", refreshToken: "ref", user: null });

    renderProtected();

    expect(screen.getByText("Projects Page")).toBeInTheDocument();
  });
});
