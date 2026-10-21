// The trackers' logos, the same shapes as in the apps themselves.
//   health  a heart-rate line that ends in a loop (a running route) with a sage dot
//   wealth  a wallet with a terracotta coin
//   trackerai  both dots side by side: the family mark

export function HealthMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 32 24" width={(size * 32) / 24} height={size} className={className} aria-hidden focusable="false">
      <path
        d="M1.5 14h6l2.5-8 4 15 3-10 2 3h4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="26.5" cy="14" r="4" fill="#8cb9a0" />
    </svg>
  );
}

export function WealthMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 32 24" width={(size * 32) / 24} height={size} className={className} aria-hidden focusable="false">
      <path
        d="M6 8.5h18a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V6.5a3 3 0 0 1 3-3h13"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="22.5" cy="15.5" r="2.6" fill="#c98055" />
    </svg>
  );
}

export function TrackerAIMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 40 24" width={(size * 40) / 24} height={size} className={className} aria-hidden focusable="false">
      <path
        d="M2 14h5l2.2-7 3.6 13 2.7-8.5 1.8 2.5H22"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="27" cy="14" r="4" fill="#8cb9a0" />
      <circle cx="35.5" cy="14" r="4" fill="#c98055" />
    </svg>
  );
}
