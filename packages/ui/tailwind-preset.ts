import type { Config } from "tailwindcss";

// The Tailwind theme of both apps (@trackerai/ui/tailwind-preset). Every colour points to a CSS variable from the shared base.css, where the light and the
// dark theme live — Tailwind classes stay theme-blind. The names are the app's
// own (surface, ink-muted, pos/neg/warn/info, c1..c6); the alias layer in
// the shared base.css ties them to the Meridian tokens.
//
// text/gain/loss/approx are in the rgb(var(--x-rgb)/<alpha-value>) form because
// pages use them with an opacity modifier (text-text/50, bg-gain/10); a bare
// var() cannot take a /50.
const preset: Partial<Config> = {
  theme: {
    extend: {
      colors: {
        primary: "var(--brand)",
        bg: "var(--bg)",
        "bg-secondary": "var(--surface-2)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        "surface-sunk": "var(--surface-sunk)",
        "surface-ink": "var(--surface-ink)",
        border: "var(--border)",
        "border-strong": "var(--border-strong)",
        text: "rgb(var(--ink-rgb) / <alpha-value>)",
        ink: "rgb(var(--ink-rgb) / <alpha-value>)",
        "ink-muted": "var(--ink-muted)",
        "on-ink": "var(--text-on-ink)",
        "on-ink-muted": "var(--text-on-ink-muted)",
        brand: "var(--brand)",
        "brand-2": "var(--brand-2)",
        "brand-tint": "var(--brand-tint)",
        pos: "rgb(var(--pos-rgb) / <alpha-value>)",
        "pos-tint": "var(--pos-tint)",
        neg: "rgb(var(--neg-rgb) / <alpha-value>)",
        "neg-tint": "var(--neg-tint)",
        warn: "var(--warn)",
        "warn-tint": "var(--warn-tint)",
        info: "var(--info)",
        "info-tint": "var(--info-tint)",
        // Gain/loss are the same semantic pair as pos/neg and so follow the same token.
        gain: "rgb(var(--pos-rgb) / <alpha-value>)",
        loss: "rgb(var(--neg-rgb) / <alpha-value>)",
        // Quality grades on the Allocation tab.
        proxy: "var(--chart-5)",
        approx: "rgb(var(--approx-rgb) / <alpha-value>)",
      },
      // Meridian stops at 10px, except pills. `rounded` (8) is the card, `rounded-md`
      // (6) the button and the input field, `rounded-xl` (10) the dialog.
      borderRadius: {
        DEFAULT: "var(--radius-lg)",
        xs: "var(--radius-xs)",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-md)",
        xl: "var(--radius-xl)",
        "2xl": "var(--radius-xl)",
      },
      fontFamily: {
        display: ["var(--font-display)"],
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      boxShadow: {
        card: "var(--shadow-2)",
        float: "var(--shadow-3)",
        dialog: "var(--shadow-4)",
      },
      maxWidth: {
        content: "var(--content-max)",
        measure: "var(--measure)",
      },
      spacing: {
        sidebar: "var(--sidebar-w)",
        page: "var(--gutter-page)",
      },
    },
  },
};

export default preset;
