import { test } from "node:test";
import assert from "node:assert/strict";
import { barAt, beatAt, DEFAULT_PRACTICE, nextSpeed, rangeTicks } from "./practice.ts";

const bars = [0, 1, 2, 3, 4].map((i) => ({ start: i * 3840, duration: 3840 }));

test("loop range in ticks, in any order, clamped to the song", () => {
  assert.deepEqual(rangeTicks(bars, 2, 3), { startTick: 3840, endTick: 11520 });
  assert.deepEqual(rangeTicks(bars, 3, 2), { startTick: 3840, endTick: 11520 });
  assert.deepEqual(rangeTicks(bars, 4, 99), { startTick: 11520, endTick: 19200 });
  assert.equal(rangeTicks(bars, 9, 12), null);
});

test("the trainer speeds up per pass up to the target", () => {
  const p = { ...DEFAULT_PRACTICE, step: 0.05, target: 0.8 };
  assert.equal(nextSpeed(0.6, p, "tab"), 0.65);
  assert.equal(nextSpeed(0.78, p, "tab"), 0.8);
  assert.equal(nextSpeed(0.8, p, "tab"), 0.8);
  // the video only has quarter steps
  assert.equal(nextSpeed(0.5, { ...p, target: 1 }, "video"), 0.75);
  assert.equal(nextSpeed(1, { ...p, target: 1 }, "video"), 1);
});

test("bars and beats for the metronome", () => {
  assert.equal(barAt(bars, 0), 0);
  assert.equal(barAt(bars, 3839), 0);
  assert.equal(barAt(bars, 3840), 1);
  assert.equal(barAt(bars, 99999), 4);
  assert.deepEqual(beatAt(bars, 3840 + 960 * 2 + 5, 960), { bar: 1, beat: 2 });
});
