// The logomark: three strings of a tab with a note on the middle one, half hidden: a tab read in the dark.
//
//   the strings  `currentColor`, the same colour as the text next to it
//   the note     `--logo-accent`, by default the theme's dusk

export default function Logomark({ height, className }: { height: number; className?: string }) {
  return (
    <svg viewBox="0 0 32 24" height={height} width={Math.round((height * 32) / 24)} className={className} aria-hidden focusable="false">
      <path d="M2 5h28M2 12h28M2 19h28" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" />
      <circle cx="20" cy="12" r="5" fill="var(--logo-accent, var(--brand-500))" />
    </svg>
  );
}
