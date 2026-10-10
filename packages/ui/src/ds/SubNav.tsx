"use client";

// A page's tabs on a phone: a row of their own below the top bar, across the
// whole width, every tab a 44px target. On a wide screen the same tabs are in the
// top bar itself (app/(app)/layout.tsx) and this row is hidden. The active tab
// scrolls into view, so on a long row you see where you are.

import { useEffect, useRef } from "react";
import Tabs, { type TabItem } from "./Tabs";

export default function SubNav({ items, value, label }: { items: TabItem[]; value?: string; label: string }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    ref.current?.querySelector(".ds-tab--active")?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [value]);
  return (
    <nav ref={ref} className="ds-subnav no-scrollbar lg:hidden" aria-label={label}>
      <Tabs items={items} value={value} ariaLabel={label} />
    </nav>
  );
}
