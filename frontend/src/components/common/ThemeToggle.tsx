import { AnimatePresence, motion } from "motion/react";
import { Moon, Sun } from "lucide-react";
import { useRef } from "react";

import { useTheme } from "@/hooks/useTheme";
import { themeIcon } from "@/lib/motion";

/** Switches the application between light and dark.
 *
 * Accessibility (Phase 13): it is a real `<button>`, so it is keyboard
 * reachable and activates on Enter/Space for free. Its accessible name
 * says what pressing it will *do* ("Switch to dark theme"), not what
 * the current state is, and it carries `aria-pressed` so a screen
 * reader can also report the state. The label is on the control
 * itself — never tooltip-only — and focus is visible.
 *
 * The icon swap is a small cross-fade with a slight rotation; a full
 * spin would be a flourish on a control people press often.
 *
 * The switch itself is a circular reveal that grows from this button
 * (Sprint 9K.4). The button reports its own centre rather than using
 * the pointer position, so keyboard activation — where there is no
 * pointer — gets exactly the same animation as a click.
 */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const next = theme === "dark" ? "light" : "dark";

  function handleClick() {
    const rect = buttonRef.current?.getBoundingClientRect();
    toggle(
      rect && rect.width > 0
        ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
        : undefined,
    );
  }

  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={handleClick}
      aria-label={`Switch to ${next} theme`}
      aria-pressed={theme === "dark"}
      title={`Switch to ${next} theme`}
      className="relative flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={theme}
          variants={themeIcon}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="absolute inset-0 flex items-center justify-center"
        >
          {theme === "dark" ? (
            <Moon className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Sun className="h-4 w-4" aria-hidden="true" />
          )}
        </motion.span>
      </AnimatePresence>
    </button>
  );
}
