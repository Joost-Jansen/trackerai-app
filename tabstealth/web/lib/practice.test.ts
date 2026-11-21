import { test } from "node:test";
import assert from "node:assert/strict";
import { barAt, beatAt, DEFAULT_PRACTICE, nextSpeed, rangeTicks, typedBar, videoLoop } from "./practice.ts";

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
  // the video steps like the tab, up to and including the last steps before 100%
  const v = { ...p, target: 1 };
  assert.equal(nextSpeed(0.75, v, "video"), 0.8);
  assert.equal(nextSpeed(0.85, v, "video"), 0.9);
  assert.equal(nextSpeed(0.9, v, "video"), 0.95);
  assert.equal(nextSpeed(0.95, v, "video"), 1);
  assert.equal(nextSpeed(1, v, "video"), 1);
  // YouTube's smallest step is 5%: a 2% step becomes 5% there, a 10% step stays 10%
  assert.equal(nextSpeed(0.6, { ...v, step: 0.02 }, "video"), 0.65);
  assert.equal(nextSpeed(0.6, { ...v, step: 0.1 }, "video"), 0.7);
});

test("bars and beats for the metronome", () => {
  assert.equal(barAt(bars, 0), 0);
  assert.equal(barAt(bars, 3839), 0);
  assert.equal(barAt(bars, 3840), 1);
  assert.equal(barAt(bars, 99999), 4);
  assert.deepEqual(beatAt(bars, 3840 + 960 * 2 + 5, 960), { bar: 1, beat: 2 });
});

test("a typed bar number: empty while typing, within the song", () => {
  assert.equal(typedBar("", 20), null); // emptied with backspace: no bar yet
  assert.equal(typedBar("12", 20), 12);
  assert.equal(typedBar("99", 20), 20);
  assert.equal(typedBar("0", 20), 1);
  assert.equal(typedBar("1a2", 20), 12);
});

test("the video loop counts one pass per jump back, however long the old time lingers", () => {
  const s = { armed: true, lastJump: 0 };
  const end = 10;
  assert.deepEqual(videoLoop(s, 9.5, end, 1000), { jump: false, pass: false });
  assert.deepEqual(videoLoop(s, 10, end, 1100), { jump: true, pass: true });
  // the player still says 10 for a while (a seek, loading): no second pass, as long as it takes
  assert.deepEqual(videoLoop(s, 10.1, end, 1500), { jump: false, pass: false });
  assert.deepEqual(videoLoop(s, 10.2, end, 2400), { jump: false, pass: false });
  // back inside the loop: the next end is the next pass
  assert.deepEqual(videoLoop(s, 4, end, 2500), { jump: false, pass: false });
  assert.deepEqual(videoLoop(s, 10, end, 9000), { jump: true, pass: true });
  // a jump that did not take is tried again after 1.5 s, without counting a pass
  assert.deepEqual(videoLoop(s, 10.5, end, 10600), { jump: true, pass: false });
});
