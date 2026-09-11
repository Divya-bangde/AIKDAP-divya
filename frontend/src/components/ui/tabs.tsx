import * as TabsPrimitive from "@radix-ui/react-tabs";
import { motion } from "motion/react";
import * as React from "react";

import { layoutSpring } from "@/lib/motion";
import { cn } from "@/lib/utils";

/* Built on Radix Tabs rather than hand-rolled: it supplies the
 * roving-tabindex keyboard behaviour (arrow keys, Home/End) and the
 * `role`/`aria-selected`/`aria-controls` wiring that a `<div>`-based
 * tab bar would have to reimplement — and would reimplement subtly
 * wrong. Motion only adds the sliding indicator on top. */

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn("inline-flex w-fit items-center gap-1 rounded-full bg-secondary p-1 print:hidden", className)}
    {...props}
  />
));
TabsList.displayName = "TabsList";

export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger> & { isActive: boolean }
>(({ className, isActive, children, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "relative rounded-full px-4 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground",
      className,
    )}
    {...props}
  >
    {/* A segmented control: the active pill slides between segments
     * instead of an underline on a divider rule. */}
    {isActive && (
      <motion.span
        layoutId="workspace-tab-indicator"
        transition={layoutSpring}
        className="absolute inset-0 rounded-full bg-card shadow-subtle"
      />
    )}
    <span className="relative z-10">{children}</span>
  </TabsPrimitive.Trigger>
));
TabsTrigger.displayName = "TabsTrigger";

export const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = "TabsContent";
