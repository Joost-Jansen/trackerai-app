"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtEu, fmtEuro } from "@/lib/format";
import { Button, Figure, Section } from "@/components/ds";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import AllocationBars, {
  type AllocationStatus,
  DeviationLegend,
} from "@/components/rebalancing/AllocationBars";
import { tr, trx } from "@/lib/i18n";

// Rebalancing — where your portfolio stands against your target allocation, and
// how your next deposit closes that gap fastest. A port of the old Streamlit
// app.py:1118-1525; every split, deviation and traffic light comes from the
// backend, which calculates them with app.py's own arithmetic
// (services/rebalancing_service.py).
//
// The four Plotly figures that were here are gone. They drew exactly the same
// four numbers as the tiles below them — category, current %, target %,
// deviation in percentage points — one as bars, the other as text.
// AllocationBars does both in one row.

const CATEGORIES = ["Stocks", "Bonds"] as const;
const MARKETS = ["US", "Europe", "Emerging Markets"] as const;

// The backend calculates and stores in English (rebalancing_service.CATEGORIES
// and MARKET_BUCKETS are keys in the database); the page shows the user's language.
const CATEGORY_NL: Record<string, string> = { Stocks: tr("Shares"), Bonds: tr("Bonds") };
const MARKET_NL: Record<string, string> = {
  US: "VS",
  Europe: tr("Europe"),
  "Emerging Markets": tr("Emerging markets"),
};

type Allocation = {
  targets: Record<string, number>;
  positions: { isin: string; name: string; value: number; category: string }[];
  by_category: Record<string, number>;
  current_pcts: Record<string, number>;
  total_value: number;
  status: Record<string, AllocationStatus>;
};

type Split = {
  recommendations: Record<string, number>;
  after_pcts: Record<string, number>;
  after_values: Record<string, number>;
  new_total: number;
  after_status: Record<string, AllocationStatus>;
};

type Market = {
  targets: Record<string, number>;
  by_market: Record<string, number>;
  current_pcts: Record<string, number>;
  equity_value: number;
  other_value: number;
  status: Record<string, AllocationStatus>;
};

/** A euro amount field. min-h-10 on a phone: a 44px touch target. */
function AmountField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-wrap items-center gap-2 text-[13px]">
      {label}
      <input
        type="number"
        min={0}
        step={100}
        value={value}
        onChange={(e) => onChange(Math.max(0, Number(e.target.value)))}
        className="ds-input num w-28"
      />
    </label>
  );
}

/** A target slider with its percentage next to it. */
function TargetSlider({
  label,
  value,
  onChange,
  // No "(%)" after the labels: the percentage is already to the right of the
  // slider. With those three characters "Opkomende markten" wrapped to two lines
  // and pushed the slider askew.
  labelWidth = "w-32 md:w-40",
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  labelWidth?: string;
}) {
  return (
    <label className="flex items-center gap-3 text-[13px]">
      <span className={`${labelWidth} shrink-0`}>{label}</span>
      <input
        type="range"
        min={0}
        max={100}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="min-w-0 flex-1"
        style={{ accentColor: "var(--brand-500)" }}
      />
      <span className="num w-10 shrink-0 text-right font-semibold">{value}%</span>
    </label>
  );
}

function SaveButton({
  pending,
  disabled,
  onClick,
  children,
  primary = true,
}: {
  pending: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  primary?: boolean;
}) {
  return (
    <Button
      variant={primary ? "primary" : "secondary"}
      onClick={onClick}
      disabled={disabled || pending}
      className="flex-none"
    >
      {pending ? tr("Saving…") : children}
    </Button>
  );
}

/** The share of the deposit that goes to one bucket. */
function SplitTile({
  label,
  amount,
  share,
}: {
  label: string;
  amount: number;
  share: number;
}) {
  return (
    <Figure
      label={label}
      value={fmtEuro(amount)}
      note={tr("{0} of your deposits", fmtEu(share, { decimals: 0, suffix: "%" }))}
    />
  );
}

export default function RebalancingPage() {
  const queryClient = useQueryClient();
  const [stockTarget, setStockTarget] = useState<number | null>(null);
  const [categories, setCategories] = useState<Record<string, string>>({});
  const [amount, setAmount] = useState(1000);
  const [marketTargets, setMarketTargets] = useState<Record<string, number> | null>(null);
  const [marketAmount, setMarketAmount] = useState(500);

  const allocation = useQuery({
    queryKey: ["rb-allocation"],
    queryFn: () => api.get<Allocation>("/api/rebalancing/allocation"),
  });
  const market = useQuery({
    queryKey: ["rb-market"],
    queryFn: () => api.get<Market>("/api/rebalancing/market"),
  });
  const split = useQuery({
    queryKey: ["rb-split", amount],
    queryFn: () => api.get<Split>(`/api/rebalancing/next-investment?amount=${amount}`),
    enabled: amount > 0,
  });
  const marketSplit = useQuery({
    queryKey: ["rb-market-split", marketAmount],
    queryFn: () => api.get<Split>(`/api/rebalancing/market/next-investment?amount=${marketAmount}`),
    enabled: marketAmount > 0,
  });

  // Seed the editable state from the server once, then leave it to the user —
  // re-seeding on every refetch would yank the slider out from under them.
  useEffect(() => {
    if (allocation.data && stockTarget === null) setStockTarget(allocation.data.targets.Stocks);
    if (allocation.data && Object.keys(categories).length === 0) {
      setCategories(Object.fromEntries(allocation.data.positions.map((p) => [p.isin, p.category])));
    }
  }, [allocation.data, stockTarget, categories]);

  useEffect(() => {
    if (market.data && marketTargets === null) setMarketTargets(market.data.targets);
  }, [market.data, marketTargets]);

  const saveTargets = useMutation({
    mutationFn: (stocks: number) => api.put("/api/rebalancing/targets", { stocks }),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const saveCategories = useMutation({
    mutationFn: (cats: Record<string, string>) =>
      api.put("/api/rebalancing/categories", { categories: cats }),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const saveMarketTargets = useMutation({
    mutationFn: (targets: Record<string, number>) =>
      api.put("/api/rebalancing/market/targets", { targets }),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  if (allocation.isLoading || !allocation.data || stockTarget === null) {
    return <div className="h-40 animate-pulse rounded border border-border bg-surface-2" />;
  }

  const alloc = allocation.data;
  const bondTarget = 100 - stockTarget;
  const marketSum = marketTargets
    ? MARKETS.reduce((sum, m) => sum + (marketTargets[m] ?? 0), 0)
    : 0;

  return (
    <div className="flex flex-col gap-11">
      {/* ——— DOELVERDELING (app.py:1127-1157) ——— */}
      <Section
        label={tr("Target allocation")}
        info={
          <>{trx("Choose how much of your portfolio should be in shares. The other side is calculated automatically, so it always adds up to 100%.{0}{1}This is your choice, not advice from us. Everything on this page then calculates against this target.", <br />, <br />)}</>
        }
      >
        {/* Slider and button on one line left ~80px of slider on a phone — a control you can't aim
            at. Below sm they stack. */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
          <div className="flex-1">
            <TargetSlider label={tr("Shares")} value={stockTarget} onChange={setStockTarget} labelWidth="w-24" />
          </div>
          <SaveButton pending={saveTargets.isPending} onClick={() => saveTargets.mutate(stockTarget)}>{tr("Save target")}</SaveButton>
        </div>
        <p className="mt-2.5 text-xs text-ink-muted">{trx("Bonds: {0}, automatically the rest.", <strong className="num text-text">{bondTarget}%</strong>)}</p>
        {saveTargets.isSuccess && <p className="mt-1 text-xs text-pos">{tr("Target saved.")}</p>}
      </Section>

      {/* ——— HUIDIG VS DOEL (app.py:1222-1271) ——— */}
      <Section label={tr("Current against your target")}>
        {alloc.total_value === 0 ? (
          <p className="text-sm text-ink-muted">{trx("No prices available yet. Refresh them via {0} in the bar above.", <strong>{tr("Update")}</strong>)}</p>
        ) : (
          <>
            <AllocationBars
              rows={CATEGORIES.map((cat) => ({
                label: CATEGORY_NL[cat] ?? cat,
                currentPct: alloc.current_pcts[cat],
                targetPct: alloc.targets[cat],
                status: alloc.status[cat],
                currentEur: alloc.by_category[cat],
              }))}
            />
            <div className="mt-3.5 pt-2.5"
              style={{ borderTop: "1px solid var(--border-hairline)" }}>
              <DeviationLegend />
            </div>
          </>
        )}
      </Section>

      {/* ——— VOLGENDE INLEG (app.py:1278-1336) ——— */}
      {alloc.total_value > 0 && (
        <Section
          label={tr("Your next deposit")}
          info={
            <>{trx("Enter how much you are going to deposit. We split it over shares and bonds so your portfolio ends up as close as possible to your target.{0}{1}Selling is never suggested: it is arithmetic on one amount, not a plan to overhaul your portfolio.", <br />, <br />)}</>
          }
        >
          <AmountField label={tr("Deposit (€)")} value={amount} onChange={setAmount} />

          {amount > 0 && split.data && (
            <>
              <div className="mt-3.5 grid grid-cols-2 gap-2.5">
                {CATEGORIES.map((cat) => (
                  <SplitTile
                    key={cat}
                    label={CATEGORY_NL[cat] ?? cat}
                    amount={split.data.recommendations[cat]}
                    share={(split.data.recommendations[cat] / amount) * 100}
                  />
                ))}
              </div>

              <div className="mt-4 pt-3.5"
                style={{ borderTop: "1px solid var(--border-hairline)" }}>
                <div className="ds-eyebrow mb-2.5 block">{trx("Allocation after this deposit of {0}", fmtEuro(amount))}</div>
                <AllocationBars
                  rows={CATEGORIES.map((cat) => ({
                    label: CATEGORY_NL[cat] ?? cat,
                    currentPct: split.data.after_pcts[cat],
                    targetPct: alloc.targets[cat],
                    status: split.data.after_status[cat],
                    currentEur: split.data.after_values[cat],
                  }))}
                />
              </div>
            </>
          )}
        </Section>
      )}

      {/* ——— POSITIES INDELEN (app.py:1164-1215) ——— */}
      <Section
        label={tr("Classify your positions")}
        info={
          <>{trx("Set each position to shares or bonds. We guess based on the name. Correct what goes wrong and click {0}.{1}{2}Your choice is saved and overrides the guess from then on, also after you upload new transactions.", <b>{tr("Save classification")}</b>, <br />, <br />)}</>
        }
      >
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>ISIN</th>
                <th className="num">{tr("Value (€)")}</th>
                <th>{tr("Category")}</th>
              </tr>
            </thead>
            <tbody>
              {alloc.positions.map((p) => (
                <tr key={p.isin}>
                  <td>{p.name}</td>
                  <td className="text-ink-muted">{p.isin}</td>
                  <td className="num">{fmtEuro(p.value)}</td>
                  <td>
                    <select
                      value={categories[p.isin] ?? p.category}
                      aria-label={tr("Category for {0}", p.name)}
                      onChange={(e) =>
                        setCategories((prev) => ({ ...prev, [p.isin]: e.target.value }))
                      }
                      className="ds-select !h-8"
                    >
                      {CATEGORIES.map((c) => (
                        <option key={c} value={c}>
                          {CATEGORY_NL[c] ?? c}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <SaveButton
            primary={false}
            pending={saveCategories.isPending}
            onClick={() => saveCategories.mutate(categories)}
          >{tr("Save classification")}</SaveButton>
          {saveCategories.isSuccess && <span className="text-xs text-pos">{tr("Classification saved.")}</span>}
        </div>
      </Section>

      {/* ——— WELKE MARKT? (app.py:1343-1525) ——— */}
      <Section
        label={tr("Which market gets your next deposit?")}
        infoLabel={tr("Explanation the market split")}
        info={
          <>{trx("You don't need to tag anything yourself here. This comes from the same looked-through holdings as the country breakdown on {0}.{1}{2}Every equity position (inside your ETF’s and individual) is classified by country of listing and added up to US, Europe or emerging markets. What falls in none of the three is shown separately under the bars.", <b>{tr("Allocation")}</b>, <br />, <br />)}</>
        }
      >
        {market.isLoading || !market.data || !marketTargets ? (
          <div className="h-32 animate-pulse rounded-sm bg-surface-2" />
        ) : (
          <>
            <div className="flex flex-col gap-2.5">
              {MARKETS.map((m) => (
                <TargetSlider
                  key={m}
                  label={MARKET_NL[m] ?? m}
                  value={marketTargets[m] ?? 0}
                  onChange={(v) => setMarketTargets((prev) => ({ ...prev!, [m]: v }))}
                />
              ))}
            </div>

            {marketSum !== 100 && (
              <p className="num mt-3 text-[13px] text-warn">{trx("{0} = {1}: slide until it adds up to 100%.", MARKETS.map((m) => `${MARKET_NL[m] ?? m} ${marketTargets[m] ?? 0}%`).join(" + "), <strong>{marketSum}%</strong>)}</p>
            )}

            <div className="mt-3 flex items-center gap-3">
              <SaveButton
                pending={saveMarketTargets.isPending}
                disabled={marketSum !== 100}
                onClick={() => saveMarketTargets.mutate(marketTargets)}
              >{tr("Save market targets")}</SaveButton>
              {saveMarketTargets.isSuccess && (
                <span className="text-xs text-pos">{tr("Market targets saved.")}</span>
              )}
            </div>

            {market.data.equity_value === 0 ? (
              <p className="mt-3.5 text-sm text-ink-muted">{trx("No prices for your equity positions yet. Refresh them via {0} above.", <strong>{tr("Update")}</strong>)}</p>
            ) : marketSum !== 100 ? (
              <p className="mt-3.5 text-sm text-ink-muted">{tr("Set your market targets to 100% together to see the analysis.")}</p>
            ) : (
              <>
                <div className="mt-4 pt-3.5"
                style={{ borderTop: "1px solid var(--border-hairline)" }}>
                  <AllocationBars
                    rows={MARKETS.map((m) => ({
                      label: MARKET_NL[m] ?? m,
                      currentPct: market.data.current_pcts[m],
                      targetPct: market.data.targets[m],
                      status: market.data.status[m],
                      currentEur: market.data.by_market[m],
                    }))}
                  />
                  <div className="mt-3.5 pt-2.5"
              style={{ borderTop: "1px solid var(--border-hairline)" }}>
                    <DeviationLegend />
                  </div>
                </div>

                {market.data.other_value > 0 && (
                  <p className="mt-3 text-xs text-ink-muted">{trx("{0} of your shares ({1}) is in other developed markets (Japan, Canada, Australia) or isn't classified: that doesn't count in the three-way split above.", <span className="num">
                      {fmtEu((market.data.other_value / market.data.equity_value) * 100, {
                        decimals: 1,
                        suffix: "%",
                      })}
                    </span>, <span className="num">{fmtEuro(market.data.other_value)}</span>)}</p>
                )}

                <div className="mt-4 pt-3.5"
                style={{ borderTop: "1px solid var(--border-hairline)" }}>
                  <span className="mb-3 flex items-center gap-1">
                    <span className="ds-eyebrow">{tr("Split your next deposit")}</span>
                    <InfoPopover label={tr("Explanation split your next deposit")}>{tr("Enter how much you are going to put into shares. We split it so the gap between the US, Europe and emerging markets closes fastest.")}</InfoPopover>
                  </span>
                  <AmountField
                    label={tr("Deposit in shares (€)")}
                    value={marketAmount}
                    onChange={setMarketAmount}
                  />

                  {marketAmount > 0 && marketSplit.data && (
                    <>
                      {/* Three columns on a phone too: ~100px per tile is enough for "€300,00", and
                          three tiles below each other cost 270px of scrolling for three numbers. */}
                      <div className="mt-3.5 grid grid-cols-3 gap-2">
                        {MARKETS.map((m) => (
                          <SplitTile
                            key={m}
                            label={MARKET_NL[m] ?? m}
                            amount={marketSplit.data.recommendations[m]}
                            share={(marketSplit.data.recommendations[m] / marketAmount) * 100}
                          />
                        ))}
                      </div>

                      <div className="mt-4 pt-3.5"
                style={{ borderTop: "1px solid var(--border-hairline)" }}>
                        <div className="ds-eyebrow mb-2.5 block">{trx("Market split after this deposit of {0}", fmtEuro(marketAmount))}</div>
                        <AllocationBars
                          rows={MARKETS.map((m) => ({
                            label: MARKET_NL[m] ?? m,
                            currentPct: marketSplit.data.after_pcts[m],
                            targetPct: market.data.targets[m],
                            status: marketSplit.data.after_status[m],
                            currentEur: marketSplit.data.after_values[m],
                          }))}
                        />
                      </div>
                    </>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </Section>
    </div>
  );
}
