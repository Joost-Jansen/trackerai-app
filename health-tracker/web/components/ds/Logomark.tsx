// The logomark: a heart-rate line that ends in a loop, a running route.
//
//   the line  `currentColor`, the same colour as the text next to it
//   the dot   `--logo-accent`, by default the theme's sage
//
// On the sidebar ds.css makes the accent lighter, because that rail is always dark.

export default function Logomark({ height, className }: { height: number; className?: string }) {
  return (
    <svg viewBox="0 0 32 24" height={height} width={Math.round((height * 32) / 24)} className={className} aria-hidden focusable="false">
      <path
        d="M1.5 14h6l2.5-8 4 15 3-10 2 3h4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="26.5" cy="14" r="4" fill="var(--logo-accent, var(--brand-500))" />
    </svg>
  );
}
