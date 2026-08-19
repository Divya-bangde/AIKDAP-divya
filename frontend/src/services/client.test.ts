import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { request } from "@/services/client";
import { useAuthStore } from "@/store/auth-store";

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe("services/client token refresh (Phase 9)", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: "expired-token",
      refreshToken: "valid-refresh-token",
      user: null,
    });
  });

  afterEach(() => {
    useAuthStore.getState().clear();
    vi.restoreAllMocks();
  });

  it("attaches the bearer token on a normal request", async () => {
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockImplementation(() => jsonResponse(200, { ok: true }));

    await request("/api/v1/auth/me");

    const [, init] = fetchSpy.mock.calls[0];
    expect((init?.headers as Record<string, string>).Authorization).toBe(
      "Bearer expired-token",
    );
  });

  it("on a 401, refreshes exactly once, retries the original request once, and succeeds", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((url: RequestInfo | URL) => {
      const path = String(url);
      if (path.endsWith("/auth/refresh")) {
        return jsonResponse(200, {
          access_token: "new-token",
          refresh_token: "new-refresh-token",
          token_type: "bearer",
        });
      }
      if (path.endsWith("/auth/me")) {
        const accessToken = useAuthStore.getState().accessToken;
        // First call happens with the stale token (still "expired-token"
        // at call time); only the retry after refresh should succeed.
        if (accessToken === "new-token") return jsonResponse(200, { id: "u1" });
        return jsonResponse(401, { detail: "Could not validate credentials" });
      }
      throw new Error(`unexpected fetch to ${path}`);
    });

    const result = await request<{ id: string }>("/api/v1/auth/me");

    expect(result).toEqual({ id: "u1" });
    expect(useAuthStore.getState().accessToken).toBe("new-token");
    // /auth/me called twice (original + one retry), /auth/refresh called once.
    const meCalls = fetchSpy.mock.calls.filter(([url]: [RequestInfo | URL, ...unknown[]]) => String(url).endsWith("/auth/me"));
    const refreshCalls = fetchSpy.mock.calls.filter(([url]: [RequestInfo | URL, ...unknown[]]) =>
      String(url).endsWith("/auth/refresh"),
    );
    expect(meCalls).toHaveLength(2);
    expect(refreshCalls).toHaveLength(1);
  });

  it("clears the session and does not retry endlessly when refresh itself fails", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((url: RequestInfo | URL) => {
      const path = String(url);
      if (path.endsWith("/auth/refresh")) {
        return jsonResponse(401, { detail: "Refresh token expired" });
      }
      return jsonResponse(401, { detail: "Could not validate credentials" });
    });

    await expect(request("/api/v1/auth/me")).rejects.toMatchObject({ status: 401 });

    expect(useAuthStore.getState().accessToken).toBeNull();
    // /auth/me is called exactly once — the failed refresh must not
    // trigger a second retry loop.
    const meCalls = fetchSpy.mock.calls.filter(([url]: [RequestInfo | URL, ...unknown[]]) => String(url).endsWith("/auth/me"));
    expect(meCalls).toHaveLength(1);
  });
});
