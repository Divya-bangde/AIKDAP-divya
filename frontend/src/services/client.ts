import { parseApiError, type ApiError } from "@/lib/api-error";
import { getAuthTokens, useAuthStore } from "@/store/auth-store";
import type { components } from "@/types/api";

/** The ONLY module in this frontend that calls `fetch`. Every other
 * service module (auth/projects/assets/research/health) goes through
 * `request()`/`requestForm()` here — see
 * `test_services_do_not_call_fetch_directly` for the guard. */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

if (import.meta.env.DEV && !BASE_URL) {
  // Fails loudly at import time rather than producing confusing
  // "Failed to fetch relative URL" errors deep in a component tree.
  throw new Error(
    "VITE_API_BASE_URL is not set. Copy frontend/.env.example to frontend/.env.",
  );
}

type TokenPair = components["schemas"]["TokenPair"];

let refreshInFlight: Promise<string | null> | null = null;

/** Exchange the stored refresh token for a new access token exactly
 * once per concurrent burst of 401s — `refreshInFlight` coalesces
 * simultaneous callers instead of firing N refresh requests. Returns
 * the new access token, or `null` if refresh failed (expired/invalid
 * refresh token), in which case the caller clears the session. */
async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;

  const { refreshToken } = getAuthTokens();
  if (!refreshToken) return null;

  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) return null;
      const tokens = (await response.json()) as TokenPair;
      useAuthStore.getState().setSession({
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
      });
      return tokens.access_token;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Skip the Authorization header — only `login`/`register` need this. */
  auth?: boolean;
}

async function doFetch(path: string, init: RequestInit): Promise<Response> {
  return fetch(`${BASE_URL}${path}`, init);
}

/** JSON request/response. Attaches the bearer token unless
 * `auth: false`, and on a 401 attempts exactly one silent refresh +
 * retry before surfacing the error (Phase 9's "prevent refresh
 * loops" — `isRetry` guarantees a second 401 is never retried). */
export async function request<T>(
  path: string,
  { method = "GET", body, auth = true }: RequestOptions = {},
): Promise<T> {
  return requestInternal<T>(path, { method, body, auth }, false);
}

async function requestInternal<T>(
  path: string,
  { method, body, auth }: Required<RequestOptions>,
  isRetry: boolean,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) {
    const { accessToken } = getAuthTokens();
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  }

  const response = await doFetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && auth && !isRetry) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return requestInternal<T>(path, { method, body, auth }, true);
    }
    useAuthStore.getState().clear();
  }

  if (!response.ok) {
    throw (await parseApiError(response)) satisfies ApiError;
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Multipart upload — the one request shape `request()` cannot make
 * (no JSON body, no Content-Type header to set manually so the
 * browser can append the multipart boundary). Same 401/refresh/retry
 * contract as `request()`. */
export async function requestForm<T>(
  path: string,
  formData: FormData,
  isRetry = false,
): Promise<T> {
  const headers: Record<string, string> = {};
  const { accessToken } = getAuthTokens();
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await doFetch(path, { method: "POST", headers, body: formData });

  if (response.status === 401 && !isRetry) {
    const newToken = await refreshAccessToken();
    if (newToken) return requestForm<T>(path, formData, true);
    useAuthStore.getState().clear();
  }

  if (!response.ok) {
    throw (await parseApiError(response)) satisfies ApiError;
  }

  return (await response.json()) as T;
}
