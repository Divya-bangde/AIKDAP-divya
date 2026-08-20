import { cn } from "@/lib/utils";

/**
 * AIKDAP's brand mark (Sprint 9K.4 revisit).
 *
 * This is not a new asset: it is `public/favicon.svg` — the "A" as a
 * single ascending peak — pulled out into a component so it can be the
 * *same* mark everywhere the product shows its identity, rather than
 * the plain letter-in-a-box that had drifted into use in the nav,
 * login panel and landing header while the real mark sat unused as a
 * browser-tab icon. One glyph, one meaning: a single point interpreted
 * from many directions — the same idea `KnowledgeNetwork` draws out at
 * hero scale.
 *
 * Inline SVG rather than an `<img src="/favicon.svg">`: it needs to
 * take `currentColor`-independent fixed brand colours at any size
 * without a network request, and it is small enough (a handful of path
 * commands) that inlining costs nothing a request wouldn't have cost
 * more of.
 */
export function AikdapMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="AIKDAP"
      className={cn("h-8 w-8 shrink-0", className)}
    >
      <rect width="32" height="32" rx="7" fill="hsl(var(--primary))" />
      <path
        d="M16 7L24 24H20.5L18.7 20H13.3L11.5 24H8L16 7ZM16 12.8L14.2 17H17.8L16 12.8Z"
        fill="hsl(var(--primary-foreground))"
      />
    </svg>
  );
}
