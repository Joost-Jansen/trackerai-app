"use client";

// Trends, performance: predicted race times, longest run, records and races (components/trends/TrendsView.tsx; the tabs are in lib/nav.ts).

import TrendsView from "@/components/trends/TrendsView";

export default function Page() {
  return <TrendsView tab="performance" />;
}
