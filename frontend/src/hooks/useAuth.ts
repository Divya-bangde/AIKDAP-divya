import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import * as authService from "@/services/auth";
import { useAuthStore } from "@/store/auth-store";

/** The single hook every page/component uses for auth state. Wraps
 * the Zustand store (session tokens) with a `GET /auth/me` query
 * (the authoritative source for "who is this and are they still
 * valid") — a token can exist in storage yet be expired/rejected, so
 * `isAuthenticated` reflects a confirmed profile fetch, not merely
 * "a token string is present". */
export function useAuth() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const storedUser = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const clearStore = useAuthStore((state) => state.clear);
  const queryClient = useQueryClient();

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const user = await authService.currentUser();
      setUser(user);
      return user;
    },
    enabled: Boolean(accessToken),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const logout = useCallback(() => {
    clearStore();
    queryClient.clear();
  }, [clearStore, queryClient]);

  return {
    user: meQuery.data ?? storedUser,
    isAuthenticated: Boolean(accessToken) && !meQuery.isError,
    isLoading: Boolean(accessToken) && meQuery.isLoading,
    logout,
  };
}
