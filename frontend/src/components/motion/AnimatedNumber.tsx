import { animate, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

/** Counts from 0 up to a real value supplied by the backend.
 *
 * The animation only affects *how the number arrives on screen* — the
 * destination is always the exact value passed in, and the final
 * committed render is that value, never a rounded or interpolated one.
 * Nothing here fabricates or estimates a count.
 *
 * Returns nothing at all when `value` is undefined, so a failed or
 * in-flight query renders its own state rather than a fake zero. */
export function AnimatedNumber({ value, className }: { value?: number; className?: string }) {
  const prefersReducedMotion = useReducedMotion();
  const [display, setDisplay] = useState(value ?? 0);
  const previous = useRef(value ?? 0);

  useEffect(() => {
    if (value === undefined) return;

    if (prefersReducedMotion) {
      setDisplay(value);
      previous.current = value;
      return;
    }

    const controls = animate(previous.current, value, {
      duration: 0.6,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (latest) => setDisplay(Math.round(latest)),
      // Guarantees the exact target value is what finally renders,
      // rather than whatever the last interpolated frame rounded to.
      onComplete: () => setDisplay(value),
    });
    previous.current = value;
    return () => controls.stop();
  }, [value, prefersReducedMotion]);

  if (value === undefined) return null;

  return <span className={className}>{display}</span>;
}
