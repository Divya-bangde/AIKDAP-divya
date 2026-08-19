import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        "border-strong": "hsl(var(--border-strong))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        sunken: "hsl(var(--sunken))",
        elevated: "hsl(var(--elevated))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        // The AI / active-processing state. Its own hue on purpose, so
        // "a model is working" never reads as "selected" or "done".
        ai: {
          DEFAULT: "hsl(var(--ai))",
          foreground: "hsl(var(--ai-foreground))",
          soft: "hsl(var(--ai-soft))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 4px)",
        sm: "calc(var(--radius) - 8px)",
      },
      fontFamily: {
        // Interface and prose. Inter is chosen because it disappears —
        // at 12–14px, next to scores and chunk ids, legibility beats
        // personality.
        sans: [
          "Inter Variable",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        // Display. Space Grotesk carries the brand at large sizes; it
        // is deliberately NOT the body face, because its character
        // becomes noise below ~20px.
        display: [
          "Space Grotesk Variable",
          "Inter Variable",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        // System mono only — no webfont download. Used for machine
        // values (model ids, chunk references, scores) so they read as
        // data rather than prose.
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        /* A hierarchy, not a size ramp (Sprint 9K.4).
         *
         * Three things separate the tiers, and size is only one of
         * them: as type gets larger, tracking gets *tighter* and
         * leading gets *shorter*. That inverse relationship is what
         * makes large type read as designed rather than as zoomed —
         * default tracking at 6rem looks like a browser default,
         * because it is one.
         *
         * The three top tiers are set in the display face and are used
         * exclusively on the public entry experience. `title`,
         * `section` and `label` are the working application's scale and
         * are unchanged in role from 9K.2. */
        hero: [
          "clamp(3.5rem, 11vw, 8rem)",
          { lineHeight: "0.88", letterSpacing: "-0.045em", fontWeight: "500" },
        ],
        editorial: [
          "clamp(2.25rem, 5.6vw, 4rem)",
          { lineHeight: "0.98", letterSpacing: "-0.035em", fontWeight: "500" },
        ],
        // The closing statement. Larger than a section heading and
        // smaller than the wordmark, so the page ends on a note that is
        // clearly a conclusion rather than a tenth section.
        statement: [
          "clamp(2.75rem, 6.5vw, 5rem)",
          { lineHeight: "0.95", letterSpacing: "-0.04em", fontWeight: "500" },
        ],
        headline: [
          "clamp(1.6rem, 3vw, 2.375rem)",
          { lineHeight: "1.08", letterSpacing: "-0.028em", fontWeight: "500" },
        ],
        // Supporting copy on the entry experience. Larger and looser
        // than application body text on purpose: reading posture on a
        // marketing page is different from scanning posture in a tool.
        lede: ["clamp(1rem, 1.35vw, 1.1875rem)", { lineHeight: "1.62", letterSpacing: "-0.008em" }],

        display: ["2.5rem", { lineHeight: "1.1", letterSpacing: "-0.03em", fontWeight: "600" }],
        title: ["1.5rem", { lineHeight: "1.2", letterSpacing: "-0.02em", fontWeight: "600" }],
        section: ["1rem", { lineHeight: "1.35", letterSpacing: "-0.01em", fontWeight: "600" }],
        label: ["0.6875rem", { lineHeight: "1.2", letterSpacing: "0.08em", fontWeight: "600" }],
        // Section markers on the entry experience ("01 / THE PROBLEM").
        // Very wide tracking is what makes small uppercase read as a
        // deliberate index rather than as shouting.
        eyebrow: ["0.75rem", { lineHeight: "1.2", letterSpacing: "0.24em", fontWeight: "500" }],
      },
      boxShadow: {
        // Resolved per theme from CSS variables (see `index.css`), so
        // `shadow-raised` means "one step of elevation" in both themes
        // rather than one theme's literal colour values.
        subtle: "var(--shadow-subtle)",
        raised: "var(--shadow-raised)",
        float: "var(--shadow-float)",
      },
    },
  },
  plugins: [],
} satisfies Config;
