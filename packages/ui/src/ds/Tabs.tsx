// Three kinds of tabs, one component — and the choice between the three is about
// content, not looks:
//
//   underline   switches between views of the same subject
//               (Positions · Details). Sits in the header of the screen.
//   quiet       a period or a filter, right next to the thing it filters
//               (1M · 6M · 1Y). Never as chrome at the top of the page.
//   segmented   a compact switch within a block. Only there.
//
// The active underline tab gets an ink stroke, the active quiet tab a hairline in
// the brand colour.

export type TabItem = { id: string; label: React.ReactNode; href?: string };

import Link from "next/link";

export default function Tabs({
  items,
  value,
  onChange,
  variant = "underline",
  ariaLabel,
  className = "",
}: {
  items: (string | TabItem)[];
  value?: string;
  /** Leave out when the tabs carry `href` — then the tab navigates instead of switching. */
  onChange?: (id: string) => void;
  variant?: "underline" | "quiet" | "segmented";
  ariaLabel?: string;
  className?: string;
}) {
  const norm: TabItem[] = items.map((i) => (typeof i === "string" ? { id: i, label: i } : i));

  if (variant === "segmented") {
    return (
      <div className={`ds-segmented ${className}`} role="group" aria-label={ariaLabel}>
        {norm.map((i) => (
          <button
            key={i.id}
            type="button"
            aria-pressed={i.id === value}
            onClick={() => onChange?.(i.id)}
            className={`ds-segmented__item ${i.id === value ? "ds-segmented__item--active" : ""}`}
          >
            {i.label}
          </button>
        ))}
      </div>
    );
  }

  const cls = `ds-tabs ${variant === "quiet" ? "ds-tabs--quiet" : ""} ${className}`;

  return (
    <div className={cls} role={ariaLabel ? "group" : undefined} aria-label={ariaLabel}>
      {norm.map((i) => {
        const active = i.id === value;
        const tabClass = `ds-tab ${active ? "ds-tab--active" : ""}`;
        // A tab with its own address is a link, not a button: that is what a bookmark,
        // the keyboard and the middle mouse button need.
        return i.href ? (
          <Link key={i.id} href={i.href} aria-current={active ? "page" : undefined} className={tabClass}>
            {i.label}
          </Link>
        ) : (
          <button key={i.id} type="button" aria-pressed={active} onClick={() => onChange?.(i.id)} className={tabClass}>
            {i.label}
          </button>
        );
      })}
    </div>
  );
}
