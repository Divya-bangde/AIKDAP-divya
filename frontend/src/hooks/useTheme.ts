import { useCallback, useEffect, useState } from "react";

import { useThemeStore, type Theme } from "@/store/theme-store";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** The OS-level colour preference, or `"light"` when the browser
 * cannot tell us (jsdom, very old browsers). Read defensively because
 * `matchMedia` is absent in the test environment. */
function systemTheme(): Theme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "light";
  }
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

/** Applies a theme to the document.
 *
 * Tailwind is configured with `darkMode: ["class"]`, so the entire
 * palette switches on the presence of one class on `<html>`. Also sets
 * `color-scheme` so the browser's own chrome — form controls,
 * scrollbars, the canvas behind an overscroll — matches; without it a
 * dark page still flashes white scrollbars.
 */
export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
}

/** Whether the user has asked the OS for reduced motion. Read at the
 * moment of the interaction rather than cached, so toggling the system
 * setting takes effect without a reload. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** How long the theme reveal takes. Long enough to read as a
 * transition, short enough that a control people press often never
 * feels like it is making them wait (the brief's 300–600ms window). */
const THEME_TRANSITION_MS = 480;

/** The point the new theme should grow from, in viewport pixels. */
export interface RevealOrigin {
  x: number;
  y: number;
}

/**
 * Applies a theme as an expanding circular reveal from `origin`.
 *
 * The effect is the View Transitions API's, not ours: the browser
 * snapshots the page before and after the class change, and we animate
 * a `clip-path` circle on the *new* snapshot so the incoming theme is
 * uncovered outward from the toggle button. Nothing is faked — both
 * frames are real renderings of the real document.
 *
 * Three cases fall back to an instant switch, all of them correct:
 *
 *   - the user asked for reduced motion (Phase 9 — mandatory),
 *   - the browser has no View Transitions API (Firefox, older Safari),
 *   - we have no origin to grow from (keyboard activation of a control
 *     that reported no geometry).
 *
 * In every case the theme still changes; only the decoration is
 * dropped. The caller does not need to know which path ran.
 *
 * `commit` — the state update that records the new preference — runs
 * *inside* the transition callback rather than before it, and that
 * ordering is load-bearing. The browser captures the "before" snapshot
 * at the next rendering opportunity, which is after React has flushed
 * a state update made in an event handler. Committing first would
 * therefore let React's own apply-theme effect change the class before
 * the snapshot was taken, so both snapshots would show the new theme
 * and the reveal would animate nothing.
 */
export function applyThemeAnimated(
  theme: Theme,
  origin: RevealOrigin | undefined,
  commit: () => void,
) {
  const root = document.documentElement;

  // `startViewTransition` is not in the DOM lib TypeScript ships yet.
  const start = (
    document as Document & {
      startViewTransition?: (callback: () => void) => { ready: Promise<void> };
    }
  ).startViewTransition;

  if (!start || !origin || prefersReducedMotion() || typeof root.animate !== "function") {
    commit();
    applyTheme(theme);
    return;
  }

  const transition = start.call(document, () => {
    commit();
    applyTheme(theme);
  });

  // The circle has to reach the furthest corner of the viewport, or the
  // old theme stays visible in whichever corner is furthest from the
  // button — which, since the button lives in the top-right, is the
  // bottom-left in practice.
  const radius = Math.hypot(
    Math.max(origin.x, window.innerWidth - origin.x),
    Math.max(origin.y, window.innerHeight - origin.y),
  );

  transition.ready
    .then(() => {
      root.animate(
        {
          clipPath: [
            `circle(0px at ${origin.x}px ${origin.y}px)`,
            `circle(${radius}px at ${origin.x}px ${origin.y}px)`,
          ],
        },
        {
          duration: THEME_TRANSITION_MS,
          easing: "cubic-bezier(0.4, 0, 0.2, 1)",
          pseudoElement: "::view-transition-new(root)",
        },
      );
    })
    .catch(() => {
      /* A transition can be skipped (a second toggle interrupts the
       * first). The class change has already been applied by then, so
       * there is nothing to recover — only the animation is lost. */
    });
}

/** Resolves and applies the application's theme.
 *
 * Resolution order (Phase 15): an explicit user choice always wins;
 * with no explicit choice, the OS preference is followed live — the
 * `change` listener means a user who never picked a theme follows
 * their system when it flips at sunset, rather than being pinned to
 * whatever it was when the tab opened.
 *
 * This hook does not know about the landing page's dark-only rule.
 * That is deliberate: `useForcedTheme` handles it separately so the
 * override is visible where it applies, and the user's real
 * preference is never overwritten to achieve it. */
export function useTheme() {
  const preference = useThemeStore((state) => state.preference);
  const setPreference = useThemeStore((state) => state.setPreference);
  const [system, setSystem] = useState<Theme>(systemTheme);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) => setSystem(event.matches ? "dark" : "light");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const theme: Theme = preference ?? system;

  /** Switches theme, revealing the new one outward from `origin` when
   * the browser and the user's motion preference allow it. Callers pass
   * the centre of the control that was pressed; omitting it (or a
   * browser without the API) degrades to an instant switch. */
  const toggle = useCallback(
    (origin?: RevealOrigin) => {
      const next: Theme = theme === "dark" ? "light" : "dark";
      applyThemeAnimated(next, origin, () => setPreference(next));
    },
    [theme, setPreference],
  );

  return { theme, preference, setPreference, toggle, isSystemDriven: preference === null };
}

/** Pins the theme while a component is mounted, then releases it.
 *
 * Used by the landing page, which is dark-only by design (Phase 16)
 * even for a user whose saved application preference is light. It sets
 * the store's transient `override` rather than touching the DOM
 * directly, so the single resolver in `useApplyTheme` still decides —
 * and the user's stored preference is never written to, so entering
 * the app returns them to exactly the theme they chose.
 */
export function useForcedTheme(forced: Theme) {
  const setOverride = useThemeStore((state) => state.setOverride);

  useEffect(() => {
    setOverride(forced);
    return () => setOverride(null);
  }, [forced, setOverride]);
}

/** Resolves and applies the effective theme. Mounted once, at the app
 * root — the only place that writes the theme to the document. */
export function useApplyTheme() {
  const { theme } = useTheme();
  const override = useThemeStore((state) => state.override);
  const effective = override ?? theme;

  useEffect(() => {
    applyTheme(effective);
  }, [effective]);

  return effective;
}
