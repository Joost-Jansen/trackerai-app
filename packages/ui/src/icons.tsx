// The line set — strokes only, never an emoji. The stroke follows currentColor,
// so the text colour around it colours them along.
//
// Stroke width 1.5 and not 2: Meridian prescribes that, and the reason shows as
// soon as you put an icon next to a line of text — at 2 the glyph is heavier than
// the letters next to it and draws attention to itself instead of supporting the
// label. Icons are in --text-faint; only the active navigation glyph gets the
// brand colour.
//
// Sizes: 16 in chrome, 15 in a button, 22 in an empty state.

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function TrendingUpIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 17l6-6 4 4 8-8" />
      <path d="M17 7h4v4" />
    </Icon>
  );
}

export function TrendingDownIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 7l6 6 4-4 8 8" />
      <path d="M17 17h4v-4" />
    </Icon>
  );
}

export function CalendarIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3" y="4.5" width="18" height="16.5" rx="2" />
      <path d="M3 9.5h18M8 2.5v4M16 2.5v4" />
    </Icon>
  );
}

export function NewspaperIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 5h13v15H5a1 1 0 0 1-1-1z" />
      <path d="M17 8h3v10a2 2 0 0 1-2 2" />
      <path d="M7 9h7M7 12.5h7M7 16h4" />
    </Icon>
  );
}

export function UploadIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 15V3M7 8l5-5 5 5" />
      <path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
    </Icon>
  );
}

export function RefreshIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M21 12a9 9 0 1 1-3-6.7L21 8" />
      <path d="M21 3v5h-5" />
    </Icon>
  );
}

export function MoonIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </Icon>
  );
}

export function SunIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.4 1.4M17.6 17.6L19 19M19 5l-1.4 1.4M6.4 17.6L5 19" />
    </Icon>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Icon>
  );
}

export function ClockIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Icon>
  );
}

export function InboxIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 12h4l2 3h4l2-3h4" />
      <path d="M5.5 5h13l2.5 7v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-7z" />
    </Icon>
  );
}

export function DownloadIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 3v12M7 10l5 5 5-5" />
      <path d="M4 19v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" transform="translate(0 -2)" />
    </Icon>
  );
}

export function FolderIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </Icon>
  );
}

/** Two opposed arrows — "this control swaps between two things". */
export function SwapIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M7 4v16" />
      <path d="M4 7l3-3 3 3" />
      <path d="M17 20V4" />
      <path d="M14 17l3 3 3-3" />
    </Icon>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-5" />
      <path d="M12 8h.01" />
    </Icon>
  );
}

// The question mark variant. The same circle at the same radius as InfoIcon,
// because the two are never far apart: the "i" belongs to one number, the "?" to
// a whole screen. Only what is inside differs, and that is exactly the difference
// in reach the user must be able to see.
export function HelpIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.6 9.4a2.5 2.5 0 0 1 4.86.83c0 1.67-2.5 2.5-2.5 2.5" />
      <path d="M12 16.5h.01" />
    </Icon>
  );
}

export function ChevronLeftIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M15 5l-7 7 7 7" />
    </Icon>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9 5l7 7-7 7" />
    </Icon>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5 9l7 7 7-7" />
    </Icon>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </Icon>
  );
}

// ---------------------------------------------------------------------------
// Navigation: one glyph per destination in the sidebar, and the hamburger that
// unfolds it on a phone.
// ---------------------------------------------------------------------------

export function MenuIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Icon>
  );
}

/** Today — the overview of surfaces. */
export function LayoutIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </Icon>
  );
}

/** Portfolio — a list of positions. */
export function ListIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01" />
    </Icon>
  );
}

/** Returns — a line that climbs. */
export function ChartLineIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 4v15a1 1 0 0 0 1 1h15" />
      <path d="M7.5 15.5l4-4.5 3 2.5 4.5-6" />
    </Icon>
  );
}

/** Allocation — the distribution bar itself, in miniature. */
export function SegmentsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3" y="9.5" width="7" height="5" rx="1.5" />
      <rect x="11.5" y="9.5" width="4.5" height="5" rx="1.5" />
      <rect x="17.5" y="9.5" width="3.5" height="5" rx="1.5" />
    </Icon>
  );
}

/** Budget — a gauge: how much of the month's limit is used. */
export function GaugeIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.5 16.5a7.5 7.5 0 1 1 15 0" />
      <path d="M12 16.5l3.5-4" />
      <circle cx="12" cy="16.5" r="1" />
    </Icon>
  );
}

/** Dividend — money that comes in without you selling anything. */
export function CoinsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <ellipse cx="12" cy="6.5" rx="7" ry="2.75" />
      <path d="M5 6.5v5c0 1.5 3.1 2.75 7 2.75s7-1.25 7-2.75v-5" />
      <path d="M5 11.5v5c0 1.5 3.1 2.75 7 2.75s7-1.25 7-2.75v-5" />
    </Icon>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v2.2M12 19.3v2.2M21.5 12h-2.2M4.7 12H2.5M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6M18.7 18.7l-1.6-1.6M6.9 6.9L5.3 5.3" />
    </Icon>
  );
}

/** Accounts — a wallet: money that is not in securities. */
export function WalletIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H18a1 1 0 0 1 1 1v2" />
      <path d="M3 7.5V17a2 2 0 0 0 2 2h14a1 1 0 0 0 1-1v-2" />
      <path d="M20 9.5h-4a2.5 2.5 0 0 0 0 5h4a1 1 0 0 0 1-1v-3a1 1 0 0 0-1-1Z" />
    </Icon>
  );
}

/** Spending — a tag: where the money went. */
export function TagIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M11.6 3.5H5.5A2 2 0 0 0 3.5 5.5v6.1a2 2 0 0 0 .6 1.4l7 7a2 2 0 0 0 2.8 0l6.1-6.1a2 2 0 0 0 0-2.8l-7-7a2 2 0 0 0-1.4-.6Z" />
      <path d="M7.8 7.8h.01" />
    </Icon>
  );
}

/** Net worth — a line that rises, with the areas below it. */
export function GrowthIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 19.5h18" />
      <path d="M3.5 15.5l5-5 4 3 7-7" />
      <path d="M15.5 6.5h4v4" />
    </Icon>
  );
}

export function ClipboardIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="5" y="4.5" width="14" height="16" rx="2" />
      <path d="M9 4.5V3.5h6v1M8.5 10h7M8.5 13.5h7M8.5 17h4" />
    </Icon>
  );
}

/** Done, within range: a plain tick. */
export function CheckIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Icon>
  );
}

/** Add one: a plus. */
export function PlusIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 5v14M5 12h14" />
    </Icon>
  );
}

/** Take a photo: a camera body with its lens. */
export function CameraIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.5 7.5h3l1.5-2h6l1.5 2h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z" />
      <circle cx="12" cy="13" r="3.5" />
    </Icon>
  );
}

/** Nutrition: a fork and a knife, side by side. Shared: wealth-tracker can use it for food spending too. */
export function UtensilsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M7 3.5v17M4.5 3.5V8a2.5 2.5 0 0 0 5 0V3.5" />
      <path d="M17 20.5V3.5c-2 0-3.5 2.2-3.5 5.5v3.5H17" />
    </Icon>
  );
}

/** Health: a heart with a pulse line through it. */
export function HeartIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />
      <path d="M5.5 12.5h3l1.5-2.5 2 4 1.5-2h5" />
    </Icon>
  );
}

export function WatchIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="6" y="6" width="12" height="12" rx="3" />
      <path d="M9 6V2h6v4M9 18v4h6v-4M12 9v3l2 1M18 10h2" />
    </Icon>
  );
}

export function BikeIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="5" cy="16" r="4" />
      <circle cx="19" cy="16" r="4" />
      <path d="m5 16 5-8 4 8H5l4-6h8M8 8h4M19 16l-3-11h-3" />
    </Icon>
  );
}

export function MapIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9 4.5 3.5 6.5v13l5.5-2 6 2 5.5-2v-13l-5.5 2-6-2Z" />
      <path d="M9 4.5v13M15 6.5v13" />
    </Icon>
  );
}

export function RouteIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="6" cy="18" r="2" />
      <circle cx="18" cy="6" r="2" />
      <path d="M8 18h7.5a3 3 0 0 0 0-6h-7a3 3 0 0 1 0-6H16" />
    </Icon>
  );
}

/** Two arrows chasing each other: syncing with an outside source. RefreshIcon is the single arrow: reloading. */
export function SyncIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M20 11a8 8 0 0 0-14.3-4.9L4 8" />
      <path d="M4 4v4h4" />
      <path d="M4 13a8 8 0 0 0 14.3 4.9L20 16" />
      <path d="M20 20v-4h-4" />
    </Icon>
  );
}

/** Media transport (tabstealth's player): play, pause, stop. */
export function PlayIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 5.5v13l10.5-6.5z" />
    </Icon>
  );
}

export function PauseIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8.5 5.5v13M15.5 5.5v13" />
    </Icon>
  );
}

export function StopIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="6.5" y="6.5" width="11" height="11" rx="1.5" />
    </Icon>
  );
}

/** A video: a screen with a play triangle. */
export function VideoIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3" y="5.5" width="18" height="13" rx="2" />
      <path d="M10.5 9.5v5l4-2.5z" />
    </Icon>
  );
}

/** Music: two beamed eighth notes. */
export function MusicIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9 17.5V6l10-2v11.5" />
      <circle cx="6.5" cy="17.5" r="2.5" />
      <circle cx="16.5" cy="15.5" r="2.5" />
    </Icon>
  );
}

/** Repeat / loop: two arrows chasing each other round a rectangle. */
export function RepeatIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M17 3.5l3 3-3 3" />
      <path d="M4 11.5v-2a3 3 0 0 1 3-3h13" />
      <path d="M7 20.5l-3-3 3-3" />
      <path d="M20 12.5v2a3 3 0 0 1-3 3H4" />
    </Icon>
  );
}

export function HandIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M18 11V6a2 2 0 0 0-4 0" />
      <path d="M14 10V4a2 2 0 0 0-4 0v2" />
      <path d="M10 10.5V6a2 2 0 0 0-4 0v8" />
      <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-6-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" />
    </Icon>
  );
}
