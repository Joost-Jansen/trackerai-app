// The allocation card's roll-up (lib/slices.ts) and the stacked chart's arithmetic (lib/allocation-history.ts).
//
//   node --import ./scripts/ts-resolve.mjs --test scripts/test-allocation.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { foldedSlices, OTHER, topSlices } from "../lib/slices.ts";
import { bandColours, stackBands } from "../lib/allocation-history.ts";

const s = (name, pct) => ({ name, pct });

test("the backend's own Other and the folded tail are one row, not two", () => {
  // The screenshot: an issuer "Other" of 9.7% ranked among the sectors, and a tail of 19.5% folded under the same name.
  const list = [
    s("Information Technology", 30),
    s("Financials", 15),
    s("Health Care", 12),
    s("Industrials", 10),
    s(OTHER, 9.7),
    s("Consumer Discretionary", 8),
    s("Communication Services", 7),
    s("Energy", 4.5),
    s("Materials", 3.8),
  ];
  const slices = topSlices(list);
  const others = slices.filter((x) => x.id === OTHER);
  assert.equal(others.length, 1);
  assert.equal(others[0].pct, 9.7 + 7 + 4.5 + 3.8);
  assert.equal(slices.length, 6);
  // What sits behind that row: the backend's Other and the three folded sectors.
  const folded = foldedSlices(list, slices).map((x) => x.name);
  assert.deepEqual(folded.sort(), [OTHER, "Communication Services", "Energy", "Materials"].sort());
});

test("a backend Other is never ranked as a category of its own", () => {
  const slices = topSlices([s("Europe", 40), s(OTHER, 35), s("North America", 25)]);
  assert.deepEqual(
    slices.map((x) => x.id),
    ["Europe", "North America", OTHER],
  );
});

test("six categories without an Other are drawn whole", () => {
  const list = ["A", "B", "C", "D", "E", "F"].map((n, i) => s(n, 20 - i));
  const slices = topSlices(list);
  assert.equal(slices.length, 6);
  assert.ok(slices.every((x) => x.id !== OTHER));
});

test("stacked bands start at zero and end at the sum", () => {
  const bands = stackBands([
    [60, 30, 10],
    [50, 0, 50],
  ]);
  assert.deepEqual(bands[0], [
    { lo: 0, hi: 60 },
    { lo: 60, hi: 90 },
    { lo: 90, hi: 100 },
  ]);
  assert.equal(bands[1][2].hi, 100);
  assert.equal(bands[1][1].lo, bands[1][1].hi); // an empty band has no height
});

test("Other is grey wherever it is, the rest follow the palette", () => {
  assert.deepEqual(bandColours(["a", "b", OTHER], ["c1", "c2"], OTHER, "grey"), ["c1", "c2", "grey"]);
});
