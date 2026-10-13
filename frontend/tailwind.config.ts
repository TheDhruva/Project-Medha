import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        medha: {
          bg: "var(--medha-bg)",
          warm: "var(--medha-bg-warm)",
          sidebar: "var(--medha-sidebar)",
          surface: "var(--medha-surface)",
          muted: "var(--medha-surface-muted)",
          text: "var(--medha-text)",
          secondary: "var(--medha-text-secondary)",
          tertiary: "var(--medha-text-tertiary)",
          border: "var(--medha-border)",
          strong: "var(--medha-border-strong)",
          accent: "var(--medha-accent)",
          "accent-hover": "var(--medha-accent-hover)",
          "accent-soft": "var(--medha-accent-soft)",
          "accent-ink": "var(--medha-accent-ink)",
          run: "var(--medha-run)",
          "run-soft": "var(--medha-run-soft)",
          "run-ink": "var(--medha-run-ink)",
          success: "var(--medha-success)",
          "success-ink": "var(--medha-success-ink)",
          "success-soft": "var(--medha-success-soft)",
          warning: "var(--medha-warning)",
          "warning-soft": "var(--medha-warning-soft)",
          danger: "var(--medha-danger)",
          "danger-soft": "var(--medha-danger-soft)",
          "surface-muted": "var(--medha-surface-muted)",
          "surface-soft": "var(--medha-surface-soft)",
        },
      },
      fontFamily: {
        display: ["Space Grotesk", "system-ui", "sans-serif"],
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        medha: "var(--medha-radius)",
        "medha-sm": "var(--medha-radius-sm)",
      },
      boxShadow: {
        medha: "var(--medha-shadow)",
      },
    },
  },
  plugins: [],
};
export default config;
