import assert from "node:assert/strict";
import { test } from "node:test";
import { bridge, bridgeSeries } from "../lib/net-worth-bridge.ts";

const point = (d, investments, bank, debt, extra = {}) => ({ d, investments, bank, debt, net: investments + bank + debt, ...extra });
const flow = (d, saved, to_investments = 0) => ({ d, saved, to_investments, others: 0, unlabelled: 0, bank_flow: saved - to_investments });

const points = [point("2026-01-01", 1000, 500, -2000), point("2026-01-02", 1100, 400, -2000), point("2026-01-03", 1050, 650, -1990)];
const flows = [flow("2026-01-01", 0), flow("2026-01-02", -10, 100), flow("2026-01-03", 250)];

test("starts at zero and ends where the tiles end", () => {
  const series = bridgeSeries(points, flows);
  assert.deepEqual(series[0], { d: "2026-01-01", change: 0, saved: 0, market: 0, bank: 0, debt: 0, unsplit: 0, banked: true });
  const last = series[series.length - 1];
  const tiles = bridge(points[0], points[2], flows);
  for (const k of ["change", "saved", "market", "bank", "debt"]) assert.equal(last[k], tiles[k]);
});

test("every point adds up to the change in net worth so far", () => {
  for (const s of bridgeSeries(points, flows)) {
    assert.ok(Math.abs(s.saved + s.market + s.bank + s.debt + s.unsplit - s.change) < 1e-9);
  }
});

test("market is what the holdings did, saving is what came in", () => {
  const [, day2] = bridgeSeries(points, flows);
  assert.equal(day2.saved, -10); // spent 10
  assert.equal(day2.market, 0); // the 100 more in investments was a deposit
});

test("no bank data in the stretch: market and debt still run, the rest is unsplit", () => {
  const held = [
    point("2026-01-01", 1000, 500, -2000, { portfolio: 1000, portfolio_invested: 1000 }),
    point("2026-01-02", 1050, 520, -1990, { portfolio: 1050, portfolio_invested: 1000 }),
  ];
  for (const none of [[], [flow("2026-02-01", 5)]]) {
    const [, day2] = bridgeSeries(held, none);
    assert.deepEqual(day2, { d: "2026-01-02", change: 80, saved: 0, market: 50, bank: 0, debt: 10, unsplit: 20, banked: false });
  }
});

test("without the holdings, no market to measure before the bank data", () => {
  assert.equal(bridgeSeries(points, [flow("2026-02-01", 5)]), null);
  assert.equal(bridgeSeries(points.slice(0, 1), flows), null);
});

test("bank data that starts later: market and debt from the start, saving and bank & cash unsplit until then", () => {
  // Holdings: 1000 invested; worth 1050 on day 2 (+50 market), 1100 on day 3 after 30 more went in (+20 market).
  const held = [
    point("2026-01-01", 1000, 500, -2000, { portfolio: 1000, portfolio_invested: 1000 }),
    point("2026-01-02", 1050, 520, -1990, { portfolio: 1050, portfolio_invested: 1000 }),
    point("2026-01-03", 1100, 600, -1990, { portfolio: 1100, portfolio_invested: 1030 }),
  ];
  const later = [flow("2026-01-03", 110, 30)]; // from 3 January: 2 January is the last balance before it
  const series = bridgeSeries(held, later);
  assert.deepEqual(
    series.map((s) => [s.d, s.banked]),
    [
      ["2026-01-01", false],
      ["2026-01-02", true],
      ["2026-01-03", true],
    ],
  );
  const [, day2, day3] = series;
  assert.equal(day2.market, 50);
  assert.equal(day2.debt, 10);
  assert.equal(day2.unsplit, 20); // the bank balance went up 20: saved or bank & cash, not told apart
  assert.equal(day3.market, 70);
  assert.equal(day3.unsplit, 20); // stays put once the bank data starts
  const split = bridge(held[1], held[2], later);
  assert.equal(day3.saved, split.saved);
  assert.equal(day3.bank, split.bank);
  for (const s of series) assert.ok(Math.abs(s.saved + s.market + s.bank + s.debt + s.unsplit - s.change) < 1e-9);
});
