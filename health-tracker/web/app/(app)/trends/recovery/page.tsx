"use client";

// Trends, recovery: the body's values per day or week against your own normal (components/trends/TrendsView.tsx; the
// tabs are in lib/nav.ts).

import TrendsView from "@/components/trends/TrendsView";

export default function Page() {
  return <TrendsView tab="recovery" />;
}
