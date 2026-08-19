import { motion } from "motion/react";
import type { ReactNode } from "react";

import { pageEnter, staggerContainer, staggerItem } from "@/lib/motion";

/** Wraps a routed page so it enters consistently.
 *
 * Deliberately *not* an exit animation on route change: React Router
 * swaps the element immediately, and gating navigation behind an exit
 * animation makes the app feel slower than it is. Pages arrive
 * smoothly; they leave instantly. */
export function PageTransition({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={pageEnter}
      className="flex flex-col gap-8"
    >
      {children}
    </motion.div>
  );
}

/** A block whose direct children should arrive in sequence. */
export function Stagger({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer} className={className}>
      {children}
    </motion.div>
  );
}

/** One child of a `Stagger`. */
export function StaggerItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div variants={staggerItem} className={className}>
      {children}
    </motion.div>
  );
}
