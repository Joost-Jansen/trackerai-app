// Trades grouped per day for the chart marks (lib/trade-days.ts), and the kept
// portfolio's line on the Returns chart (lib/kept-line.ts).
//
//   node --import ./scripts/ts-resolve.mjs --test scripts/test-what-if.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { tradeDays } from "../lib/trade-days.ts";
import { keptLine } from "../lib/kept-line.ts";

const t = (date, name, transaction_type, total_eur) => ({ date, name, isin: name, transaction_type, total_eur, quantity: 1 });

test("trades are grouped per day, sales first, amounts as positive euros", () => {
  const days = tradeDays([
    t("2026-10-30", "ASML", "SELL", 2000),
    t("2026-10-30", "Alphabet", "BUY", -1500),
    t("2026-10-30", "S&P 500", "SELL", 5000),
    t("2026-10-30", "Alphabet", "BUY", -400),
    t("2026-11-03", "World", "BUY", -100),
  ]);
  assert.deepEqual(days, [
    {
      d: "2026-10-30",
      kind: "sell",
      sold: { total: 7000, names: ["S&P 500", "ASML"] },
      bought: { total: 1900, names: ["Alphabet"] },
    },
    { d: "2026-11-03", kind: "buy", sold: { total: 0, names: [] }, bought: { total: 100, names: ["World"] } },
  ]);
});

test("anything that is not a buy or a sale is no trade", () => {
  assert.deepEqual(tradeDays([t("2026-01-02", "X", "DIVIDEND", 10), t("2026-01-03", "X", "BUY", null)]), [
    { d: "2026-01-03", kind: "buy", sold: { total: 0, names: [] }, bought: { total: 0, names: ["X"] } },
  ]);
});

const pts = (rows) => rows.map(([d, v]) => ({ d, v }));

test("the kept line leaves the portfolio's line on the snapshot's day", () => {
  const portfolio = pts([
    ["2026-10-28", 100],
    ["2026-10-29", 110],
    ["2026-10-30", 120],
    ["2026-11-02", 121],
  ]);
  const growth = pts([
    ["2026-10-29", 1],
    ["2026-10-30", 1.05],
    ["2026-11-02", 0.9],
  ]);
  assert.deepEqual(
    keptLine(portfolio, growth),
    pts([
      ["2026-10-29", 110],
      ["2026-10-30", 115.5],
      ["2026-11-02", 99],
    ]),
  );
});

test("a snapshot older than the period starts on the period's first day", () => {
  const portfolio = pts([
    ["2026-10-30", 200],
    ["2026-11-02", 210],
  ]);
  const growth = pts([
    ["2026-01-02", 1],
    ["2026-10-29", 1.5],
    ["2026-11-02", 1.8],
  ]);
  // Growth on the 30th carries the 29th's 1.5: 200 × 1.8 / 1.5 = 240 on the 2nd.
  assert.deepEqual(
    keptLine(portfolio, growth),
    pts([
      ["2026-10-30", 200],
      ["2026-11-02", 240],
    ]),
  );
});

test("a snapshot from a day the portfolio line doesn't have takes the last point before it", () => {
  const portfolio = pts([
    ["2026-10-30", 120],
    ["2026-11-02", 130],
  ]);
  const growth = pts([
    ["2026-11-01", 1],
    ["2026-11-02", 1.1],
  ]);
  assert.deepEqual(
    keptLine(portfolio, growth),
    pts([
      ["2026-11-01", 120],
      ["2026-11-02", 132],
    ]),
  );
});

test("no kept line after the period or without points", () => {
  assert.deepEqual(keptLine(pts([["2026-01-01", 100]]), pts([["2026-02-01", 1]])), []);
  assert.deepEqual(keptLine([], pts([["2026-02-01", 1]])), []);
  assert.deepEqual(keptLine(pts([["2026-01-01", 100]]), []), []);
});
