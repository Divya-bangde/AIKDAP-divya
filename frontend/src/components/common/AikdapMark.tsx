import { cn } from "@/lib/utils";

/**
 * AIKDAP's brand mark: a hand-drawn line sketch — an A and a K sharing
 * one stroke, inside a circle — on a solid ink tile.
 *
 * `public/favicon.svg` is the same drawing with thicker strokes for a
 * 16px browser tab. Change one, change both.
 *
 * Three choices keep thin line art legible at the 32–44px the product
 * renders it:
 *
 *   - `vector-effect: non-scaling-stroke` holds every line at 1.5 CSS
 *     px whatever size the mark is drawn. Scaled with the viewBox, lines
 *     that read well at 140px fall below a pixel at 32px and vanish.
 *   - The tile is `--brand-mark` in both themes (see `index.css`), never
 *     a theme token, so the white lines keep their contrast on either
 *     canvas.
 *   - An ink tile has no edge on a dark canvas, so it carries a faint
 *     inner rim and a top-lit sheen. The tile is the element's own CSS
 *     background rather than an SVG shape, so the rim, the sheen and the
 *     tile itself all follow whatever `rounded-*` and `shadow-*` the
 *     caller passes.
 *
 * Inline SVG rather than an `<img src="/favicon.svg">`: it resolves its
 * colours from CSS tokens and costs no network request.
 */
export function AikdapMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="-66 -66 132 132"
      fill="none"
      role="img"
      aria-label="AIKDAP"
      className={cn(
        "h-8 w-8 shrink-0 rounded-[22%] bg-[hsl(var(--brand-mark))] bg-gradient-to-b from-[hsl(var(--brand-mark-foreground)/0.1)] to-transparent ring-1 ring-inset ring-[hsl(var(--brand-mark-foreground)/0.14)]",
        className,
      )}
    >
      <g
        stroke="hsl(var(--brand-mark-foreground))"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle r="46" vectorEffect="non-scaling-stroke" />
        <path
          d="M-2.7-45.9L-33.7 31.3L34.7-30.3M-2.7-45.9L14.4 43.7M5.4-3.8L41.6 19.5"
          vectorEffect="non-scaling-stroke"
        />
      </g>
    </svg>
  );
}
