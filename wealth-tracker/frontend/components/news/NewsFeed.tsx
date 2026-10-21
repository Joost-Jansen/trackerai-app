"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EtfTopStock, NewsItem } from "@/lib/dashboard";
import NewsList from "@/components/news/NewsList";
import { Button, EmptyState, Section, Tag } from "@/components/ds";
import { NewspaperIcon, RefreshIcon } from "@trackerai/ui/icons";
import { tr } from "@/lib/i18n";

// The News tab: three headline feeds built by the backend from Finnhub and
// Alpha Vantage (see backend/app/services/news_service.py). Each tab is one
// query against /api/news/*; an empty feed renders as a calm empty state, since
// the backend returns [] on any provider failure by design.

export type NewsTab = "market" | "holdings" | "etf-top";

const TABS: { id: NewsTab; label: string; blurb: string }[] = [
  {
    id: "market",
    label: tr("Market news"),
    blurb: tr("World and market news that moves the market: tariffs, rate decisions, geopolitics."),
  },
  {
    id: "holdings",
    label: tr("My shares"),
    blurb: tr("News about the individual shares you own yourself."),
  },
  {
    id: "etf-top",
    label: tr("Top 5 in ETF's"),
    blurb: tr("News about the five largest companies you own indirectly through your ETF's."),
  },
];

function SkeletonRows() {
  const bar = { background: "var(--surface-inset)" };
  return (
    <div className="flex flex-col gap-6">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="flex flex-col gap-2">
          <div className="h-4 w-3/4 animate-pulse rounded" style={bar} />
          <div className="h-3 w-1/3 animate-pulse rounded" style={bar} />
        </div>
      ))}
    </div>
  );
}

function NothingHere({ tab }: { tab: NewsTab }) {
  return (
    <EmptyState
      icon={<NewspaperIcon className="h-[22px] w-[22px]" />}
      title={tr("Nothing to report")}
      body={
        tab === "holdings"
          ? tr("No recent news about your shares found. We look again every day.")
          : tab === "etf-top"
            ? tr("No recent news about your largest ETF positions found.")
            : tr("No market news available right now.")
      }
    />
  );
}

export default function NewsFeed({ tab }: { tab: NewsTab }) {
  const qc = useQueryClient();

  const marketQ = useQuery({
    queryKey: ["news", "market"],
    queryFn: () => api.get<{ items: NewsItem[] }>("/api/news/market"),
  });
  const holdingsQ = useQuery({
    queryKey: ["news", "holdings"],
    queryFn: () => api.get<{ items: NewsItem[] }>("/api/news/holdings"),
  });
  const etfTopQ = useQuery({
    queryKey: ["news", "etf-top"],
    queryFn: () => api.get<{ items: NewsItem[]; stocks: EtfTopStock[] }>("/api/news/etf-top"),
  });

  const refresh = useMutation({
    mutationFn: () => api.post("/api/news/refresh"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["news"] }),
  });

  const active = tab === "market" ? marketQ : tab === "holdings" ? holdingsQ : etfTopQ;
  const items = active.data?.items ?? [];
  const topStocks = etfTopQ.data?.stocks?.filter((s) => s.name) ?? [];
  const blurb = TABS.find((t) => t.id === tab)!.blurb;

  return (
    // Full width like the other pages; the list goes to two columns on a wide screen
    // so a headline stays a readable line rather than one long stripe.
    <div className="flex flex-col gap-9">
      <div className="flex justify-end">
        <Button
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          size="sm"
          icon={<RefreshIcon className={`h-[15px] w-[15px] ${refresh.isPending ? "animate-spin" : ""}`} />}
        >
          {tr("Refresh")}
        </Button>
      </div>

      {/* On the ETF feed: name the five companies the news is about. */}
      {tab === "etf-top" && topStocks.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11.5px] text-ink-muted">{tr("Largest positions:")}</span>
          {topStocks.map((st) => (
            <Tag key={st.symbol ?? st.name} outline>
              {st.name}
            </Tag>
          ))}
        </div>
      )}

      <Section
        label={TABS.find((t) => t.id === tab)!.label}
        meta={tr("{0} articles", items.length)}
        infoLabel={tr("Explanation this feed")}
        info={blurb}
      >
        {active.isLoading ? (
          <SkeletonRows />
        ) : active.isError ? (
          <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>
            {tr("The news could not load. Try again.")}
          </p>
        ) : items.length === 0 ? (
          <NothingHere tab={tab} />
        ) : (
          <NewsList items={items} showSummary={tab === "market"} />
        )}
      </Section>
    </div>
  );
}
