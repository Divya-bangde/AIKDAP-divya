import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "dark" | "light";

interface ThemeState {
  /** The user's explicit choice, or `null` when they have never made
   * one. `null` is meaningfully different from a stored value: it is
   * what makes "follow the OS" the first-visit behaviour and an
   * explicit pick permanent thereafter (Phase 15). */
  preference: Theme | null;
  /** A theme pinned by the current screen, outranking `preference`
   * while set. The landing page uses this to stay dark-only.
   *
   * Deliberately part of the store rather than a local effect in the
   * landing page: React runs child effects before parent effects, so a
   * "force dark on mount" effect in the page was being immediately
   * overwritten by the root's own apply-theme effect (observed live —
   * the landing rendered light). One resolver reading one state makes
   * the outcome independent of effect ordering.
   *
   * Never persisted: it describes where the user is right now, not
   * what they prefer. */
  override: Theme | null;
  setPreference: (theme: Theme) => void;
  clearPreference: () => void;
  setOverride: (theme: Theme | null) => void;
}

/** The application's theme preference.
 *
 * Persisted to `localStorage` through the same Zustand `persist`
 * middleware the auth session already uses — no second state library,
 * and no backend call: a display preference is not the server's
 * business (Phase 14).
 *
 * Note this stores the *preference*, not the resolved theme. Resolving
 * it against the OS setting is `useTheme`'s job, so a user who never
 * picks a theme keeps following their system as it changes rather than
 * being frozen at whatever it happened to be on their first visit. */
export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      preference: null,
      override: null,
      setPreference: (preference) => set({ preference }),
      clearPreference: () => set({ preference: null }),
      setOverride: (override) => set({ override }),
    }),
    {
      name: "aikdap-theme",
      // Only the durable preference is written to localStorage. The
      // screen-scoped override must not survive a reload, or a user who
      // refreshed on the landing page would be stuck in dark once they
      // signed in.
      partialize: (state) => ({ preference: state.preference }),
    },
  ),
);
