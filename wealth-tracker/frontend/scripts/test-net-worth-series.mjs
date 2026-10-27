import assert from "node:assert/strict";
import { test } from "node:test";
import { bridge, bridgeSeries } from "../lib/net-worth-bridge.ts";

const point = (d, investments, bank, debt, extra = {}) => ({ d, investments, bank, debt, net: investments + bank + debt, ...extra });
const flow = (d, saved, to_investments = 0) => ({ d, saved, to_investments, others: 0, unlabelled: 0, bank_flow: saved - to_investments });

const points = [point("2026-01-01", 1000, 500, -2000), point("2026-01-02", 1100, 400, -2000), point("2026-01-03", 1050, 650, -1990)];
const flows = [flow("2026-01-01", 0), flow("2026-01-02", -10, 100), flow("2026-01-03", 250)];

test("starts at zero and ends where the tiles end", () => {
  const series = bridgeSeries(points, flows);
  assert.deepEqual(series[0], { d: "2026-01-01", change: 0, saved: 0, market: 0, bank: 0, debt: 0 });
  const last = series[series.length - 1];
  const tiles = bridge(points[0], points[2], flows);
  for (const k of ["change", "saved", "market", "bank", "debt"]) assert.equal(last[k], tiles[k]);
});

test("every point adds up to the change in net worth so far", () => {
  for (const s of bridgeSeries(points, flows)) {
    assert.ok(Math.abs(s.saved + s.market + s.bank + s.debt - s.change) < 1e-9);
  }
});

test("market is what the holdings did, saving is what came in", () => {
  const [, day2] = bridgeSeries(points, flows);
  assert.equal(day2.saved, -10); // spent 10
  assert.equal(day2.market, 0); // the 100 more in investments was a deposit
});

test("nothing to split with before the bank data starts", () => {
  assert.equal(bridgeSeries(points, [flow("2026-02-01", 5)]), null);
  assert.equal(bridgeSeries(points.slice(0, 1), flows), null);
});
