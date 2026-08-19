import { Navigate, Outlet } from "react-router-dom";

import { useAuthStore } from "@/store/auth-store";

/** Guards every route except `/login`. Reactive to the Zustand store,
 * so a session cleared mid-app (an expired refresh token —
 * `services/client.ts` calls `clear()` on refresh failure) redirects
 * here on the next render without any imperative navigation call. */
export function ProtectedRoute() {
  const accessToken = useAuthStore((state) => state.accessToken);

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
