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
        background: "var(--background)",
        foreground: "var(--foreground)",
        accent: {
          500: "#10b981", // Emerald 500
          900: "#064e3b",
        }
      },
    },
  },
  plugins: [],
};
export default config;
