import { test } from "node:test";
import assert from "node:assert/strict";
import { gpString, makeClock, nearestRate } from "./sync.ts";

const bars = [0, 1, 2, 3].map((i) => ({ start: i * 3840, duration: 3840 }));
const timing = { video: "x", measure_starts: [4, 7.3, 10.6, 13.9], measure_seconds: 3.3 };

test("bar starts map onto the measured video times", () => {
  const c = makeClock(timing, bars);
  assert.equal(c.tickToTime(0), 4);
  assert.equal(c.tickToTime(3840), 7.3);
  assert.ok(Math.abs(c.tickToTime(1920) - 5.65) < 1e-9);
});

test("the last bar ends one bar length after its start", () => {
  const c = makeClock(timing, bars);
  assert.ok(Math.abs(c.tickToTime(3 * 3840 + 1920) - (13.9 + 1.65)) < 1e-9);
});

test("time to tick is the inverse, and clamps before the first bar", () => {
  const c = makeClock(timing, bars);
  for (const tick of [0, 1000, 3840, 5000, 11000]) assert.ok(Math.abs(c.timeToTick(c.tickToTime(tick)) - tick) <= 1);
  assert.equal(c.timeToTick(1), 0);
});

test("YouTube speed and string numbering helpers", () => {
  assert.equal(nearestRate(0.8), 0.75);
  assert.equal(nearestRate(1), 1);
  assert.equal(gpString(6), 1);
  assert.equal(gpString(1), 6);
});
