import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Enforcing neutral Zinc palette with Emerald as the single restrained accent.
        // Explicitly avoiding generic AI purple/blue.
        // Values come from the generated DTCG tokens (app/tokens.css); the
        // Emerald/Zinc baseline is defined once, in tokens/amc.tokens.json.
        background: "var(--background)",
        // Theme-aware page background for surfaces that opt into data-amc-theme.
        canvas: "var(--amc-semantic-color-background)",
        foreground: "var(--foreground)",
        accent: {
          DEFAULT: "var(--amc-semantic-color-accent)",
          500: "var(--amc-primitive-color-emerald-500)",
          900: "var(--amc-primitive-color-emerald-900)",
        },
        // Semantic (T2) and component (T3) tokens for new consumers.
        surface: {
          DEFAULT: "var(--amc-semantic-color-surface)",
          raised: "var(--amc-semantic-color-surface-raised)",
        },
        line: {
          DEFAULT: "var(--amc-semantic-color-border)",
          strong: "var(--amc-semantic-color-border-strong)",
        },
        fg: {
          DEFAULT: "var(--amc-semantic-color-foreground)",
          strong: "var(--amc-semantic-color-foreground-strong)",
          muted: "var(--amc-semantic-color-foreground-muted)",
        },
        status: {
          success: "var(--amc-semantic-color-status-success)",
          warning: "var(--amc-semantic-color-status-warning)",
          danger: "var(--amc-semantic-color-status-danger)",
          info: "var(--amc-semantic-color-status-info)",
        },
        "ai-trust": {
          border: "var(--amc-component-ai-trust-color-border)",
          surface: "var(--amc-component-ai-trust-color-surface)",
          label: "var(--amc-component-ai-trust-color-label)",
          detail: "var(--amc-component-ai-trust-color-detail)",
          provider: "var(--amc-component-ai-trust-color-provider)",
          degraded: "var(--amc-component-ai-trust-color-degraded)",
          unavailable: "var(--amc-component-ai-trust-color-unavailable)",
        },
      },
      // Type scale (major third, 16px base) from semantic.font.size / line-height.
      fontSize: {
        caption: ["var(--amc-semantic-font-size-caption)", { lineHeight: "var(--amc-semantic-font-line-height-body)" }],
        label: ["var(--amc-semantic-font-size-label)", { lineHeight: "var(--amc-semantic-font-line-height-body)" }],
        body: ["var(--amc-semantic-font-size-body)", { lineHeight: "var(--amc-semantic-font-line-height-body)" }],
        lead: ["var(--amc-semantic-font-size-lead)", { lineHeight: "var(--amc-semantic-font-line-height-body)" }],
        h3: ["var(--amc-semantic-font-size-h3)", { lineHeight: "var(--amc-semantic-font-line-height-title)" }],
        h2: ["var(--amc-semantic-font-size-h2)", { lineHeight: "var(--amc-semantic-font-line-height-title)" }],
        h1: ["var(--amc-semantic-font-size-h1)", { lineHeight: "var(--amc-semantic-font-line-height-heading)" }],
        display: ["var(--amc-semantic-font-size-display)", { lineHeight: "var(--amc-semantic-font-line-height-heading)" }],
        "display-lg": ["var(--amc-semantic-font-size-display-lg)", { lineHeight: "var(--amc-semantic-font-line-height-heading)" }],
      },
      // Layout rhythm on the 8px grid; Tailwind's default numeric spacing is already 4px-based.
      spacing: {
        block: "var(--amc-semantic-space-block)",
        section: "var(--amc-semantic-space-section)",
        "section-lg": "var(--amc-semantic-space-section-lg)",
      },
      borderRadius: {
        "ai-trust": "var(--amc-component-ai-trust-radius-container)",
      },
      ringColor: {
        focus: "var(--amc-semantic-color-focus-ring)",
      },
    },
  },
  plugins: [],
};
export default config;
