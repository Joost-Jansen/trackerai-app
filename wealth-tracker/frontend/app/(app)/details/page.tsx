"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtEu, fmtEuro, fmtShares } from "@/lib/format";
import EditableCell from "@/components/EditableCell";
import Disclosure from "@/components/etf/Disclosure";
import { Section, SignedValue } from "@/components/ds";
import { tr, trx } from "@/lib/i18n";

// Details — the tab you use to reconcile with DeGiro.
//
// Every column, caption and sort order follows the old Streamlit app.py:600-849;
// the numbers are formatted by lib/format.ts, which
// backend/tests/domain/test_format_parity.py pins character for character to
// charts.fmt_eu.

type Position = {
  isin: string;
  name: string;
  ticker: string | null;
  shares_held: number;
  avg_cost: number;
  total_invested: number;
  current_price: number | null;
  current_value: number | null;
  unrealized_gain: number | null;
  return_pct: number | null;
  price_fetched_at: string | null;
  /**
   * A fund on two exchanges with different prices: the price is the
   *  unit-weighted average.
   */
  price_blended?: boolean;
};

type Transaction = {
  date: string;
  name: string;
  isin: string;
  transaction_type: string;
  quantity: number;
  price: number | null;
  transaction_fee: number | null;
  total_eur: number | null;
};

type DividendPayment = {
  date: string;
  name: string;
  isin: string;
  currency_original: string | null;
  amount_original: number | null;
  gross_eur: number | null;
  tax_eur: number | null;
  net_eur: number | null;
};

type DividendByStock = {
  isin: string;
  name: string;
  payments: number;
  gross_eur: number;
  tax_eur: number;
  net_eur: number;
};

type ClosedPosition = {
  isin: string;
  name: string;
  first_buy: string | null;
  last_sell: string | null;
  total_invested: number;
  total_proceeds: number;
  realized_gain: number;
  return_pct: number;
};

export default function DetailsPage() {
  const queryClient = useQueryClient();
  const [tickerError, setTickerError] = useState<string | null>(null);
  const [savingIsin, setSavingIsin] = useState<string | null>(null);

  const positions = useQuery({
    queryKey: ["positions"],
    queryFn: () => api.get<{ positions: Position[]; priced_total: number }>("/api/positions"),
  });
  const overrides = useQuery({
    queryKey: ["ticker-overrides"],
    queryFn: () => api.get<{ overrides: Record<string, string> }>("/api/ticker-overrides"),
  });
  const transactions = useQuery({
    queryKey: ["transactions"],
    queryFn: () => api.get<{ transactions: Transaction[] }>("/api/transactions"),
  });
  const dividends = useQuery({
    queryKey: ["dividends"],
    queryFn: () =>
      api.get<{ by_stock: DividendByStock[]; payments: DividendPayment[] }>("/api/dividends"),
  });
  const closed = useQuery({
    queryKey: ["closed-positions"],
    queryFn: () => api.get<{ positions: ClosedPosition[] }>("/api/positions/closed"),
  });

  // Every table on this page reads prices, so a re-fetch invalidates all of
  // them — and the dashboard's totals behind it.
  const saveTicker = useMutation({
    mutationFn: ({ isin, ticker }: { isin: string; ticker: string }) =>
      api.put(`/api/ticker-overrides/${isin}`, { ticker }),
    onMutate: ({ isin }) => {
      setTickerError(null);
      setSavingIsin(isin);
    },
    onError: (e) => setTickerError(e instanceof ApiError ? e.message : "Could not save ticker"),
    onSettled: () => {
      setSavingIsin(null);
      queryClient.invalidateQueries();
    },
  });

  const removeOverride = useMutation({
    mutationFn: (isin: string) => api.del(`/api/ticker-overrides/${isin}`),
    onMutate: (isin) => {
      setTickerError(null);
      setSavingIsin(isin);
    },
    onSettled: () => {
      setSavingIsin(null);
      queryClient.invalidateQueries();
    },
  });

  if (positions.isLoading || !positions.data) {
    return <p className="py-10 text-sm text-ink-muted">{tr("Loading…")}</p>;
  }

  const overrideMap = overrides.data?.overrides ?? {};
  const txRows = [...(transactions.data?.transactions ?? [])].sort((a, b) =>
    b.date.localeCompare(a.date),
  );
  const payments = [...(dividends.data?.payments ?? [])].sort((a, b) => b.date.localeCompare(a.date));

  return (
    <div className="flex flex-col gap-11">
      {/* --- Huidige posities (app.py:602-651) --- */}
      <Section
        label={tr("Current positions")}
        meta={tr("total {0}", fmtEuro(positions.data.priced_total))}
        info={
          <>{trx("Exactly the prices behind every number on Today, with the moment each was fetched.{0}{1}A difference of cents per position with DeGiro is normal: Yahoo runs about a quarter of an hour behind and may quote a different exchange than the one you bought on.{2}{3}If a price is really wrong, click the ticker and enter the right one from finance.yahoo.com, for example {4} for XETRA or {5} for Amsterdam.", <br />, <br />, <br />, <br />, <code>IQQH.DE</code>, <code>VUSA.AS</code>)}</>
        }
      >
        {tickerError && (
          <p className="text-sm" style={{ color: "var(--text-loss)" }}>{tickerError}</p>
        )}

        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>ISIN</th>
                <th>Ticker</th>
                <th className="num">{tr("Quantity")}</th>
                <th className="num">{tr("Price (€)")}</th>
                <th className="num">{tr("Value (€)")}</th>
                <th className="num">{tr("Avg cost (€)")}</th>
                <th className="num">{tr("Deposited (€)")}</th>
                <th className="num">W/V (€)</th>
                <th className="num">{tr("Return %")}</th>
                <th>{tr("Price fetched")}</th>
              </tr>
            </thead>
            <tbody>
              {positions.data.positions.map((p) => {
                const overridden = p.isin in overrideMap;
                return (
                  <tr key={p.isin}>
                    <td>{p.name}</td>
                    <td className="ds-table__ticker">{p.isin}</td>
                    <td>
                      <span className="flex items-center gap-1">
                        <EditableCell
                          value={p.ticker ?? ""}
                          pending={savingIsin === p.isin}
                          placeholder={tr("e.g. IQQH.DE")}
                          ariaLabel={tr("Yahoo ticker for {0}", p.name)}
                          title={
                            overridden
                              ? tr("Set by hand. Click to change")
                              : tr("Found automatically. Click to correct")
                          }
                          onSave={(ticker) => saveTicker.mutate({ isin: p.isin, ticker })}
                        />
                        {overridden && (
                          <button
                            type="button"
                            onClick={() => removeOverride.mutate(p.isin)}
                            title={tr("Remove the manual ticker and determine it automatically again")}
                            aria-label={tr("Remove manual ticker for {0}", p.name)}
                            className="text-xs text-ink-muted hover:text-text"
                          >
                            ✕
                          </button>
                        )}
                      </span>
                    </td>
                    <td className="num">{fmtShares(p.shares_held)}</td>
                    <td className="num">
                      {fmtEuro(p.current_price, { decimals: 4 })}
                      {p.price_blended && (
                        <span
                          className="ml-1 text-xs text-ink-muted"
                          title={tr("You hold this fund on more than one exchange: this is the price weighted by the number of units per exchange.")}
                        >{tr("avg.")}</span>
                      )}
                    </td>
                    <td className="num">{fmtEuro(p.current_value)}</td>
                    <td className="num">{fmtEuro(p.avg_cost, { decimals: 4 })}</td>
                    <td className="num">{fmtEuro(p.total_invested)}</td>
                    <td className="num">
                      <SignedValue value={p.unrealized_gain} />
                    </td>
                    <td className="num">
                      <SignedValue value={p.return_pct} prefix="" suffix="%" />
                    </td>
                    <td className="text-ink-muted">{p.price_fetched_at ?? "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

      </Section>

      {/* --- Alle transacties (app.py:722-753) --- */}
      <Section label={tr("All transactions")} meta={tr("{0} rows, newest first", txRows.length)}>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>{tr("Date")}</th>
                <th>Product</th>
                <th>ISIN</th>
                <th>{tr("Kind")}</th>
                <th className="num">{tr("Quantity")}</th>
                <th className="num">{tr("Price (local)")}</th>
                <th className="num">{tr("Costs (€)")}</th>
                <th className="num">{tr("Total (€)")}</th>
              </tr>
            </thead>
            <tbody>
              {txRows.map((t, i) => (
                // No more green/red tinted rows (app.py:745-747): a coloured cell is not an
                // allowed surface treatment in this design, and the kind is already a word in
                // its own column — that reads in greyscale too.
                <tr key={`${t.isin}-${t.date}-${i}`}>
                  <td>{t.date}</td>
                  <td>{t.name}</td>
                  <td className="ds-table__ticker">{t.isin}</td>
                  <td>{t.transaction_type === "BUY" ? tr("Buy") : tr("Sell")}</td>
                  <td className="num">{fmtShares(t.quantity)}</td>
                  <td className="num">{fmtEu(t.price, { decimals: 4 })}</td>
                  <td className="num">{fmtEuro(t.transaction_fee)}</td>
                  <td className="num">{fmtEuro(t.total_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* --- Dividendbetalingen (app.py:757-809) --- */}
      <Section label={tr("Dividend payments")}>
        {dividends.data && dividends.data.by_stock.length > 0 ? (
          <>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>ISIN</th>
                    <th className="num">{tr("Payouts")}</th>
                    <th className="num">{tr("Gross (€)")}</th>
                    <th className="num">{tr("Tax (€)")}</th>
                    <th className="num">{tr("Net (€)")}</th>
                  </tr>
                </thead>
                <tbody>
                  {dividends.data.by_stock.map((d) => (
                    <tr key={d.isin}>
                      <td>{d.name}</td>
                      <td className="ds-table__ticker">{d.isin}</td>
                      <td className="num">{d.payments}</td>
                      <td className="num">{fmtEuro(d.gross_eur)}</td>
                      <td className="num">{fmtEuro(d.tax_eur)}</td>
                      <td className="num">{fmtEuro(d.net_eur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Disclosure label={tr("Show the individual dividend payments")}>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{tr("Date")}</th>
                      <th>Product</th>
                      <th>ISIN</th>
                      <th>{tr("Currency")}</th>
                      <th className="num">{tr("Amount (original)")}</th>
                      <th className="num">{tr("Gross (€)")}</th>
                      <th className="num">{tr("Tax (€)")}</th>
                      <th className="num">{tr("Net (€)")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payments.map((d, i) => (
                      <tr key={`${d.isin}-${d.date}-${i}`}>
                        <td>{d.date}</td>
                        <td>{d.name}</td>
                        <td className="ds-table__ticker">{d.isin}</td>
                        <td>{d.currency_original ?? "–"}</td>
                        <td className="num">{fmtEu(d.amount_original, { decimals: 4 })}</td>
                        <td className="num">{fmtEuro(d.gross_eur)}</td>
                        <td className="num">{fmtEuro(d.tax_eur)}</td>
                        <td className="num">{fmtEuro(d.net_eur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Disclosure>
          </>
        ) : (
          <p className="text-xs text-ink-muted">{tr("No dividend payments recorded yet.")}</p>
        )}
      </Section>

      {/* --- Gesloten posities (app.py:813-849) --- */}
      <Section label={tr("Closed positions")}>
        {closed.data && closed.data.positions.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>ISIN</th>
                  <th>{tr("First purchase")}</th>
                  <th>{tr("Last sale")}</th>
                  <th className="num">{tr("Deposited (€)")}</th>
                  <th className="num">{tr("Proceeds (€)")}</th>
                  <th className="num">{tr("Realised (€)")}</th>
                  <th className="num">{tr("Return (%)")}</th>
                </tr>
              </thead>
              <tbody>
                {closed.data.positions.map((c) => (
                  // No tinted row here either: the sign and the colour of the amount itself
                  // already say it, and those read in greyscale too.
                  <tr key={c.isin}>
                    <td>{c.name}</td>
                    <td className="ds-table__ticker">{c.isin}</td>
                    <td>{c.first_buy ?? "–"}</td>
                    <td>{c.last_sell ?? "–"}</td>
                    <td className="num">{fmtEuro(c.total_invested)}</td>
                    <td className="num">{fmtEuro(c.total_proceeds)}</td>
                    <td className="num">
                      <SignedValue value={c.realized_gain} />
                    </td>
                    <td className="num">
                      <SignedValue value={c.return_pct} prefix="" suffix="%" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">{tr("No fully closed positions found.")}</p>
        )}
      </Section>
    </div>
  );
}
