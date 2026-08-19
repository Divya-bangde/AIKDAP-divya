import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { components } from "@/types/api";

type UserRead = components["schemas"]["UserRead"];

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserRead | null;
  setSession: (tokens: { accessToken: string; refreshToken: string }) => void;
  setUser: (user: UserRead) => void;
  clear: () => void;
}

/** Holds only the frontend's own authentication session: the JWT pair
 * this backend issued, and the profile `GET /auth/me` returned.
 * Nothing provider-related (Gemini/Groq/OpenRouter/Ollama credentials,
 * database/Redis URLs) is ever stored here or anywhere in the
 * frontend — those never leave the backend process. */
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setSession: ({ accessToken, refreshToken }) =>
        set({ accessToken, refreshToken }),
      setUser: (user) => set({ user }),
      clear: () => set({ accessToken: null, refreshToken: null, user: null }),
    }),
    { name: "aikdap-auth" },
  ),
);

export function getAuthTokens() {
  const { accessToken, refreshToken } = useAuthStore.getState();
  return { accessToken, refreshToken };
}
