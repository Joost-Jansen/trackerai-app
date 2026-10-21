// Small line icons for the feature tiles, drawn in currentColor.

import type { IconName } from "./copy";

const PATHS: Record<IconName, string> = {
  sync: "M4 12a8 8 0 0 1 13.7-5.6L20 9M20 4v5h-5M20 12a8 8 0 0 1-13.7 5.6L4 15M4 20v-5h5",
  heart: "M3 12h4l2-4 4 9 2-5h6",
  trend: "M3 17l6-6 4 4 8-8M15 7h6v6",
  route: "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 17h7a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h7",
  plan: "M5 5h14v15H5zM5 9h14M9 3v4M15 3v4M8.5 13.5l2 2 4-4",
  chat: "M4 5h16v11H9l-5 4zM8 9.5h8M8 12.5h5",
  networth: "M4 19V5M4 19h16M7 15l4-4 3 3 5-6",
  spending: "M12 3v18M16.5 7.5C16 5.8 14.2 5 12 5s-4.5 1-4.5 3c0 4.5 9 2.5 9 7 0 2-2 3-4.5 3s-4.2-.9-4.8-2.7",
  tag: "M3 12V4h8l10 10-8 8zM7.5 7.5h.01",
  bank: "M3 10l9-6 9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18",
  portfolio: "M4 18l5-5 4 3 7-8M4 6h4M4 10h2",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  key: "M14.5 9.5a4 4 0 1 1-1.5-3.1L21 6v4h-3v3h-3l-1.6-1.6M8 11h.01",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  code: "M9 7l-5 5 5 5M15 7l5 5-5 5",
};

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
