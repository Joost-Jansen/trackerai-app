"use client";

// One line above the screens of a part that is still empty: where you start. The
// same line for Portfolio and Money, with a link to the right chapter in Help.
// It disappears by itself as soon as there is data, and only shows for what you
// track. Can be dismissed, per part.

import { useEffect, useState, useSyncExternalStore } from "react";
import { isExampleData, subscribeExampleData } from "@/lib/api";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { isIncluded, useOnboarding } from "@/lib/onboarding";
import { tr } from "@/lib/i18n";

const HIDDEN = "start-banner-hidden-";
const SHARE_OUT = {
  portfolio: {
    screens: ["/dashboard", "/portfolio", "/details", "/returns", "/allocation", "/rebalancing", "/dividend", "/calendar"],
    text: tr("No investments yet: export your Transactions and Account statement from DeGiro and upload them at Update."),
    href: "/help/portfolio#importing",
  },
  money: {
    screens: ["/net-worth", "/accounts", "/spending", "/categories"],
    text: tr("No accounts yet: connect your bank or upload an export via Update."),
    href: "/help/money#importing",
  },
} as const;

export default function StartBanner({ enabled }: { enabled: boolean }) {
  const pathname = usePathname();
  const q = useOnboarding(enabled);
  // During the tour's walk the page shows example data: a banner about your own
  // empty account would contradict it.
  const example = useSyncExternalStore(subscribeExampleData, isExampleData, () => false);
  const [hidden, setHidden] = useState<string[] | null>(null);
  useEffect(() => {
    try {
      setHidden(Object.keys(SHARE_OUT).filter((d) => localStorage.getItem(HIDDEN + d)));
    } catch {
      setHidden([]);
    }
  }, []);

  if (!q.data || hidden === null || example) return null;
  const part = (Object.keys(SHARE_OUT) as (keyof typeof SHARE_OUT)[]).find((d) =>
    SHARE_OUT[d].screens.some((s) => pathname === s || pathname.startsWith(`${s}/`)));
  if (!part || hidden.includes(part)) return null;
  const { status, choice } = q.data;
  const empty = part === "portfolio"
    ? status.portfolio.transactions === 0 && isIncluded(choice, "investments")
    : status.money.accounts === 0 && status.money.bank_transactions === 0 && isIncluded(choice, "money");
  if (!empty) return null;

  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-2 rounded-md px-4 py-3 text-sm"
      style={{ background: "var(--surface-inset)" }}>
      <span>
        {SHARE_OUT[part].text}{" "}
        <Link href={SHARE_OUT[part].href} className="font-semibold underline underline-offset-4">{tr("How it works")}</Link>
      </span>
      <button type="button" className="text-xs text-ink-muted underline underline-offset-4" onClick={() => {
        try { localStorage.setItem(HIDDEN + part, "1"); } catch { /* zonder opslag: alleen nu weg */ }
        setHidden((v) => [...(v ?? []), part]);
      }}>{tr("Hide")}</button>
    </div>
  );
}
