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
        foreground: "var(--foreground)",
        accent: {
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
