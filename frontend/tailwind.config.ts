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
      spacing: {
        /* The icon step between `4` (16px) and `5` (20px), used for an
         * icon sitting in a 36–40px tile.
         *
         * Four components already asked for `h-4.5 w-4.5` — but 4.5 is
         * not in Tailwind's default scale, so those classes generated no
         * CSS at all and the icons silently fell back to lucide's own
         * 24px default: oversized, and inconsistent with every other
         * icon-in-a-tile in the product. Declaring the step makes the
         * intent real rather than deleting it. */
        4.5: "1.125rem",
      },
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
        // Bento surfaces — cards, dialogs, floating panels. Deliberately
        // its own token rather than `--radius`, which sizes controls:
        // a 24px button or input reads as a toy.
        card: "1.5rem",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 4px)",
        sm: "calc(var(--radius) - 8px)",
      },
      fontFamily: {
        // One family for every role (see `styles/fonts.css`). `display`
        // stays a separate key so large type keeps a role marker, even
        // though it resolves to the same face.
        sans: ["Geist Variable", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        display: ["Geist Variable", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["Geist Mono Variable", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
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
          { lineHeight: "0.88", letterSpacing: "-0.04em", fontWeight: "500" },
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

        // The application's scale. Headlines are heavy and tight; the
        // two body sizes below are loose and slightly open, so the
        // contrast between a heading and its copy is stark.
        display: ["2.75rem", { lineHeight: "1.05", letterSpacing: "-0.035em", fontWeight: "700" }],
        title: ["1.625rem", { lineHeight: "1.15", letterSpacing: "-0.025em", fontWeight: "650" }],
        section: ["1.0625rem", { lineHeight: "1.35", letterSpacing: "-0.015em", fontWeight: "600" }],
        // 12px floor: Geist is less hinted than Inter, and 11px went soft
        // on 1080p Windows displays.
        label: ["0.75rem", { lineHeight: "1.25", letterSpacing: "0.05em", fontWeight: "600" }],
        sm: ["0.875rem", { lineHeight: "1.375rem", letterSpacing: "0.005em" }],
        xs: ["0.75rem", { lineHeight: "1.125rem", letterSpacing: "0.01em" }],
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
